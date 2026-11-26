// Coverage for the maintainer's question on the split of a batched indirect Dispatch (#2734): "If explicit DLL
// unload and reload in a live host is a supported path, that path needs teardown outside the loader lock and its
// own coverage because each reload would allocate a new cache."
//
//   startup_split_reload <path-to-d3d12_xs.dll>
//
// One process, two phases, a real unload in between. The shim is reached by LoadLibraryExW and GetProcAddress
// only: the executable does not import d3d12_xs.dll, because an import keeps a reference the loader counts and
// FreeLibrary would then never unmap the module. Both phases create their own device through
// D3D12XboxCreateDevice, run the counted case of `startup_indirect_dispatch.exe hardware count` with
// X2W_SPLIT_INDIRECT_DISPATCH=1 -- one rootless Dispatch signature, MaxCommandCount 3, a GPU-written count word
// of 3, the result word read back -- and must read back 0x31415a64. Between the phases every guest wrapper is
// released in teardown order and FreeLibrary must report success *and* the image must be gone from the loader's
// module list, otherwise the second load would hand back the first instance and nothing here would be a reload.
//
// What it proves: the reload path runs end to end on this adapter and driver, the module is really unmapped and
// mapped again, and the reloaded image builds a working split pipeline and root signature for its new device.
// What it does not prove: that the second split cache is a *new* allocation. The split cache keeps itself and
// its entries for the life of the process (split_indirect_dispatch.h) and no probe reports it, its entries or
// their objects, so this fixture cannot count caches; a cache instance that survived the reload, or one kept
// outside the module, would print exactly the same lines. Only the unmapped-then-remapped module stands in for
// it -- a freshly mapped image reinitialises its data segment, and with it the splitter pointer -- and nothing
// here observes that allocation. The first cache's entries, a root signature and a pipeline on the first
// phase's desktop device, stay allocated for the life of the process and this fixture cannot see them either.
// When FreeLibrary does not unmap the module the run stops before phase B with exit 5, so the reload is only
// measured on an image that really left the process.
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <d3dcompiler.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include "adapter_name_filter.h"
#include "startup_indirect_writer.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <memory>
#include <string>
#include <vector>

namespace {
using Microsoft::WRL::ComPtr;
using Words = std::vector<std::uint32_t>;

// The shim's entry points, all resolved at run time (see the header comment).
using XboxCreateDevice = HRESULT (WINAPI*)(IUnknown*, const void*, REFIID, void**);
using FixtureComputeRootUav = BOOL (WINAPI*)(void*, UINT, UINT64);
using RecordingScratches = UINT (WINAPI*)(void*);

struct Shim {
    HMODULE module;
    XboxCreateDevice create_device;
    FixtureComputeRootUav compute_root_uav;
    RecordingScratches recording_scratches;
};

constexpr UINT max_commands = 3;
// Word 0 pads the record to byte offset 4, so the count word is word 1 and the three records start at word 2.
constexpr UINT argument_offset = 2 * sizeof(std::uint32_t);
constexpr UINT count_offset = sizeof(std::uint32_t);
constexpr UINT result_bytes = 2 * sizeof(std::uint32_t);
// The result word the counted case must read back with a count of 3 (see the expected-word loop in run_counted).
constexpr std::uint32_t expected_result = 0x31415a64;

// The `count` shader of tests/startup_indirect_dispatch.cpp, reduced to the entry this fixture runs: the GPU
// writes the count word and three Dispatch records, and the consumer adds one term per group of every record
// the count lets through.
constexpr char shader[] = R"(
RWByteAddressBuffer data : register(u0);

void write_records(uint count) {
    data.Store(4, count);
    data.Store3(8, uint3(2, 1, 1));
    data.Store3(20, uint3(1, 2, 1));
    data.Store3(32, uint3(1, 1, 3));
}
[numthreads(1, 1, 1)]
void write_count3() { write_records(3); }

[numthreads(1, 1, 1)]
void consume_args(uint3 group : SV_GroupID) {
    uint previous;
    data.InterlockedAdd(0, 1 + group.x + 10 * group.y + 100 * group.z, previous);
}
)";

ComPtr<ID3DBlob> compile(const char* entry)
{
    ComPtr<ID3DBlob> code, errors;
    const HRESULT hr = D3DCompile(shader, sizeof(shader) - 1, nullptr, nullptr, nullptr, entry, "cs_5_0",
                                  0, 0, &code, &errors);
    if (FAILED(hr) && errors) std::fprintf(stderr, "%s\n", static_cast<const char*>(errors->GetBufferPointer()));
    check(hr, entry);
    return code;
}

ComPtr<ID3D12PipelineState> pipeline(ID3D12Device* device, ID3D12RootSignature* root, const char* entry)
{
    const auto code = compile(entry);
    D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root;
    desc.CS = {code->GetBufferPointer(), code->GetBufferSize()};
    ComPtr<ID3D12PipelineState> result;
    check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&result)), entry);
    return result;
}

template <typename Method>
Method slot(IUnknown* object, unsigned index)
{
    return reinterpret_cast<Method>((*reinterpret_cast<void***>(object))[index]);
}

ComPtr<IUnknown> guest_pipeline(ID3D12Device* guest, ID3D12RootSignature* root)
{
    const auto code = compile("consume_args");
    struct {
        alignas(void*) D3D12_PIPELINE_STATE_SUBOBJECT_TYPE root_type = D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_ROOT_SIGNATURE;
        ID3D12RootSignature* root;
        alignas(void*) D3D12_PIPELINE_STATE_SUBOBJECT_TYPE cs_type = D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_CS;
        D3D12_SHADER_BYTECODE code;
    } stream{D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_ROOT_SIGNATURE, root,
             D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_CS, {code->GetBufferPointer(), code->GetBufferSize()}};
    const D3D12_PIPELINE_STATE_STREAM_DESC desc{sizeof(stream), &stream};
    using Create = HRESULT (WINAPI*)(IUnknown*, const D3D12_PIPELINE_STATE_STREAM_DESC*, REFIID, void**);
    ComPtr<IUnknown> result;
    check(slot<Create>(guest, 86)(guest, &desc, __uuidof(ID3D12PipelineState),
                                 reinterpret_cast<void**>(result.GetAddressOf())), "create guest compute pipeline");
    return result;
}

// The `count` case of startup_indirect_dispatch.cpp with the GPU-written count 3, no rejection control and no
// follow-up: same buffers, same writer, same word-by-word verification. The one addition is the label, so the
// result line says which phase produced it.
bool run_counted(const Shim& shim, ID3D12Device* device, ID3D12Device* guest, ID3D12RootSignature* root,
                 ID3D12RootSignature* guest_root, ID3D12PipelineState* writer, IUnknown* consumer,
                 ID3D12CommandSignature* signature, const char* label)
{
    const Words initial{0xa5a5a5a5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x31415926, 0x5a5a5a5a};
    // What the GPU writer stores after the padding word: the count word, then the three Dispatch records.
    const Words record{3, 2, 1, 1, 1, 2, 1, 1, 1, 3};
    const UINT total_bytes = static_cast<UINT>(initial.size() * sizeof(std::uint32_t));
    const UINT argument_bytes = static_cast<UINT>((initial.size() - 2) * sizeof(std::uint32_t));
    auto upload = make_buffer(device, total_bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback = make_buffer(device, total_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    const auto free_memory = [](void* memory) { VirtualFree(memory, 0, MEM_RELEASE); };
    const std::unique_ptr<void, decltype(free_memory)> memory_backing(
        VirtualAlloc(nullptr, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE), free_memory);
    if (!memory_backing) throw std::bad_alloc();
    D3D12_RESOURCE_DESC argument_desc{};
    argument_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    argument_desc.Width = argument_bytes;
    argument_desc.Height = argument_desc.DepthOrArraySize = argument_desc.MipLevels = 1;
    argument_desc.SampleDesc.Count = 1;
    argument_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    argument_desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    using Place = HRESULT (WINAPI*)(IUnknown*, void*, const D3D12_RESOURCE_DESC*, UINT, const void*, REFIID, void**);
    ComPtr<IUnknown> guest_arguments;
    check(slot<Place>(guest, 133)(guest, static_cast<char*>(memory_backing.get()) + 4, &argument_desc,
                                  D3D12_RESOURCE_STATE_COMMON, nullptr, __uuidof(ID3D12Resource),
                                  reinterpret_cast<void**>(guest_arguments.GetAddressOf())), "place guest argument buffer");
    const auto arguments = indirect_native_object<ID3D12Resource>(device, guest, guest_arguments.Get());
    auto result = make_buffer(device, result_bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST,
                              D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    void* memory = nullptr;
    const D3D12_RANGE untouched{0, 0};
    check(upload->Map(0, &untouched, &memory), "map upload");
    std::memcpy(memory, initial.data(), total_bytes);
    upload->Unmap(0, nullptr);

    ComPtr<ID3D12CommandAllocator> allocator;
    check(guest->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "create guest allocator");
    using CreateList = HRESULT (WINAPI*)(IUnknown*, const void*, IUnknown*, IUnknown*, REFIID, void**);
    const UINT list_desc[]{D3D12_COMMAND_LIST_TYPE_DIRECT, 2, 1, 0};
    ComPtr<IUnknown> guest_list;
    check(slot<CreateList>(guest, 73)(guest, list_desc, allocator.Get(), nullptr, __uuidof(ID3D12GraphicsCommandList),
                                     reinterpret_cast<void**>(guest_list.GetAddressOf())), "create guest command list");
    using Reset = HRESULT (WINAPI*)(IUnknown*, IUnknown*, void*, void*);
    check(slot<Reset>(guest_list.Get(), 139)(guest_list.Get(), allocator.Get(), nullptr, nullptr), "reset guest command list");
    const auto native_list = indirect_native_object<ID3D12GraphicsCommandList>(device, guest, guest_list.Get());
    auto* list = native_list.Get();
    transition(list, arguments.Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
    list->CopyBufferRegion(arguments.Get(), 0, upload.Get(), 0, argument_bytes);
    list->CopyBufferRegion(result.Get(), 0, upload.Get(), argument_bytes, result_bytes);
    transition(list, result.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    list->SetComputeRootSignature(root);
    transition(list, arguments.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    record_indirect_writer(list, writer, arguments.Get());
    transition(list, arguments.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
    list->CopyBufferRegion(readback.Get(), 0, arguments.Get(), 0, argument_bytes);
    transition(list, arguments.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COMMON);

    using Bind = void (WINAPI*)(IUnknown*, IUnknown*);
    slot<Bind>(guest_list.Get(), 25)(guest_list.Get(), consumer);
    slot<Bind>(guest_list.Get(), 33)(guest_list.Get(), guest_root);
    // Bound through the shim, which sets it again after the compute pass of the split. If the shim has no
    // matching UAV parameter for the bound guest root, bind on the desktop list as the other fixture does.
    if (!shim.compute_root_uav(guest_list.Get(), 0, result->GetGPUVirtualAddress()))
        list->SetComputeRootUnorderedAccessView(0, result->GetGPUVirtualAddress());
    using Execute = void (WINAPI*)(IUnknown*, IUnknown*, UINT, IUnknown*, UINT64, IUnknown*, UINT64);
    slot<Execute>(guest_list.Get(), 61)(guest_list.Get(), signature, max_commands, guest_arguments.Get(),
                                        argument_offset, guest_arguments.Get(), count_offset);
    transition(list, result.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
    list->CopyBufferRegion(readback.Get(), argument_bytes, result.Get(), 0, result_bytes);
    using Close = HRESULT (WINAPI*)(IUnknown*);
    check(slot<Close>(guest_list.Get(), 9)(guest_list.Get()), "close guest command list");
    // A retained scratch is what says the split branch ran rather than the native multi-command call: in this
    // path only the split retains one (the rectangle-list converter is the other user of this counter, and this
    // recording has no rect list).
    const UINT scratches = shim.recording_scratches(guest_list.Get());
    if (scratches != 1) {
        std::fprintf(stderr, "reload %s: recording holds %u split scratch buffers after Close, expected 1\n", label,
                     scratches);
        return false;
    }
    std::printf("reload %s: split scratch held=%u, so the count was split instead of run natively\n", label, scratches);
    const D3D12_COMMAND_QUEUE_DESC queue_desc{};
    ComPtr<ID3D12Fence> fence;
    check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "create completion fence");
    ComPtr<ID3D12CommandQueue> queue;
    check(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)), "create queue");
    ID3D12CommandList* submitted[]{list};
    queue->ExecuteCommandLists(1, submitted);
    check(queue->Signal(fence.Get(), 1), "signal completion fence");
    check(fence->SetEventOnCompletion(1, nullptr), "wait for completion");
    check(device->GetDeviceRemovedReason(), "GPU completion");

    const D3D12_RANGE read{0, total_bytes};
    check(readback->Map(0, &read, &memory), "map readback");
    Words observed(initial.size());
    std::memcpy(observed.data(), memory, total_bytes);
    readback->Unmap(0, &untouched);
    Words expected = initial;
    std::copy(record.begin(), record.end(), expected.begin() + 1);
    // Word 2..10 hold the three records. The GPU count word lowers the number run, never raises it.
    const std::size_t result_word = initial.size() - 2;
    const std::uint32_t executed = (std::min)(expected[1], max_commands);
    for (std::uint32_t i = 0; i < executed; ++i)
        for (std::uint32_t z = 0; z < expected[4 + 3 * i]; ++z)
            for (std::uint32_t y = 0; y < expected[3 + 3 * i]; ++y)
                for (std::uint32_t x = 0; x < expected[2 + 3 * i]; ++x)
                    expected[result_word] += 1 + x + 10 * y + 100 * z;
    std::printf("reload %s: count word=%u, executed=%u, result=0x%08x (expected 0x%08x)\n", label, observed[1],
                executed, observed[result_word], expected[result_word]);
    for (std::size_t i = 0; i < expected.size(); ++i) {
        if (observed[i] == expected[i]) continue;
        std::fprintf(stderr, "reload %s: word %zu: got 0x%08x, expected 0x%08x\n", label, i, observed[i], expected[i]);
        return false;
    }
    if (expected[result_word] != expected_result) {
        std::fprintf(stderr, "reload %s: this case should read back 0x%08x, computed 0x%08x\n", label, expected_result,
                     expected[result_word]);
        return false;
    }
    return true;
}

// The same assertion as the end of the count-mode fixture: no stored message of severity ERROR or worse.
bool debug_clean(ID3D12Device* device, const char* label)
{
    ComPtr<ID3D12InfoQueue> info;
    check(device->QueryInterface(IID_PPV_ARGS(&info)), "get debug message queue");
    for (UINT64 i = 0; i < info->GetNumStoredMessages(); ++i) {
        SIZE_T bytes = 0;
        check(info->GetMessage(i, nullptr, &bytes), "get debug message size");
        std::vector<char> storage(bytes);
        auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
        check(info->GetMessage(i, message, &bytes), "get debug message");
        if (message->Severity <= D3D12_MESSAGE_SEVERITY_ERROR) {
            std::fprintf(stderr, "reload %s: D3D12 debug message %u: %s\n", label,
                         static_cast<unsigned>(message->ID), message->pDescription);
            return false;
        }
    }
    return true;
}

// One phase: create a device through the freshly loaded shim, run the counted case, then release every object
// the shim created -- newest first, the guest device before the desktop one it wraps -- before returning. A
// wrapper left behind would call into unmapped memory after the unload, so the teardown is the point of the
// fixture, not cleanup at the end of a run.
bool run_phase(const Shim& shim, IDXGIAdapter1* adapter, bool debug_layer, const char* label)
{
    bool verified = false;
    {
        ComPtr<ID3D12Device> device;
        check(shim.create_device(adapter, nullptr, __uuidof(ID3D12Device),
                                 reinterpret_cast<void**>(device.GetAddressOf())),
              "create desktop device through d3d12_xs");
        // The guest device reads these when it is created, so they are set after the desktop device exists.
        SetEnvironmentVariableA("X2W_D3D12_PERMISSIVE", "1");
        SetEnvironmentVariableA("X2W_D3D12_LIST_NOOP", "1");
        SetEnvironmentVariableA("X2W_D3D12_RENDER", "1");
        const std::array<unsigned char, 64> parameters{};
        ComPtr<ID3D12Device> guest;
        check(shim.create_device(adapter, parameters.data(), __uuidof(ID3D12Device),
                                 reinterpret_cast<void**>(guest.GetAddressOf())),
              "create guest device");

        // Parameter 0 is the UAV at u0, exactly as in the count case.
        D3D12_ROOT_PARAMETER parameters_desc[1]{};
        parameters_desc[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
        parameters_desc[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        const D3D12_ROOT_SIGNATURE_DESC desc{1, parameters_desc, 0, nullptr, D3D12_ROOT_SIGNATURE_FLAG_NONE};
        const auto make_root = [&](ID3D12Device* owner) {
            ComPtr<ID3DBlob> serialized;
            check(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, nullptr), "serialize root");
            ComPtr<ID3D12RootSignature> root;
            check(owner->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(),
                                             IID_PPV_ARGS(&root)), "create root");
            return root;
        };
        auto root = make_root(device.Get());
        auto guest_root = make_root(guest.Get());
        D3D12_INDIRECT_ARGUMENT_DESC argument{D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH};
        const D3D12_COMMAND_SIGNATURE_DESC signature_desc{sizeof(D3D12_DISPATCH_ARGUMENTS), 1, &argument, 0};
        ComPtr<ID3D12CommandSignature> signature;
        check(guest->CreateCommandSignature(&signature_desc, nullptr, IID_PPV_ARGS(&signature)),
              "create guest command signature");
        auto writer = pipeline(device.Get(), root.Get(), "write_count3");
        auto consumer = guest_pipeline(guest.Get(), guest_root.Get());

        verified = run_counted(shim, device.Get(), guest.Get(), root.Get(), guest_root.Get(), writer.Get(),
                               consumer.Get(), signature.Get(), label);
        if (verified && debug_layer) verified = debug_clean(device.Get(), label);

        // Teardown, in the order the shim's objects depend on each other: what the guest created, the guest
        // device, then the desktop device it was made from.
        signature.Reset();
        consumer.Reset();
        writer.Reset();
        guest_root.Reset();
        root.Reset();
        guest.Reset();
        device.Reset();
    }
    return verified;
}

std::wstring wide_path(const char* text)
{
    const int length = MultiByteToWideChar(CP_ACP, 0, text, -1, nullptr, 0);
    if (length <= 1) return std::wstring();
    std::wstring wide(static_cast<std::size_t>(length), L'\0');
    if (!MultiByteToWideChar(CP_ACP, 0, text, -1, wide.data(), length)) return std::wstring();
    // -1 includes the terminating null; keeping it would put a null inside the path.
    wide.resize(static_cast<std::size_t>(length) - 1);
    return wide;
}

// LOAD_WITH_ALTERED_SEARCH_PATH needs an absolute path, so a run from another directory still finds the file.
std::wstring absolute(const std::wstring& path)
{
    std::wstring full(MAX_PATH, L'\0');
    for (;;) {
        const DWORD length = GetFullPathNameW(path.c_str(), static_cast<DWORD>(full.size()), full.data(), nullptr);
        if (!length) return std::wstring();
        if (length < full.size()) {
            full.resize(length);
            return full;
        }
        full.resize(length);
    }
}

Shim load(const std::wstring& path)
{
    Shim shim{};
    shim.module = LoadLibraryExW(path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!shim.module) {
        std::fprintf(stderr, "LoadLibraryExW(%ls) failed: %lu\n", path.c_str(),
                     static_cast<unsigned long>(GetLastError()));
        return Shim{};
    }
    shim.create_device = reinterpret_cast<XboxCreateDevice>(GetProcAddress(shim.module, "D3D12XboxCreateDevice"));
    shim.compute_root_uav =
        reinterpret_cast<FixtureComputeRootUav>(GetProcAddress(shim.module, "x2w_d3d12_fixture_compute_root_uav"));
    shim.recording_scratches =
        reinterpret_cast<RecordingScratches>(GetProcAddress(shim.module, "x2w_d3d12_recording_scratches"));
    if (!shim.create_device || !shim.compute_root_uav || !shim.recording_scratches) {
        std::fputs("d3d12_xs.dll does not export D3D12XboxCreateDevice, x2w_d3d12_fixture_compute_root_uav and "
                   "x2w_d3d12_recording_scratches\n", stderr);
        FreeLibrary(shim.module);
        return Shim{};
    }
    return shim;
}

// The loader has no API for a module's reference count. GetModuleHandleExW answers whether an image is mapped,
// and UNCHANGED_REFCOUNT keeps the answer free of the reference the call would otherwise take.
HMODULE module_at(void* address)
{
    HMODULE owner = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            reinterpret_cast<LPCWSTR>(address), &owner))
        return nullptr;
    return owner;
}

HMODULE module_by_name(const wchar_t* name)
{
    HMODULE owner = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, name, &owner)) return nullptr;
    return owner;
}

// FreeLibrary's answer says the count reached zero, not that the image went away. Both lookups below are the
// measurement: the name, and the address of an entry point this run resolved from the module.
bool unload(const Shim& shim, const char* label)
{
    void* const entry = reinterpret_cast<void*>(shim.create_device);
    if (module_at(entry) != shim.module) {
        std::fprintf(stderr, "reload %s unload: the export does not resolve inside the loaded module\n", label);
        return false;
    }
    if (!FreeLibrary(shim.module)) {
        std::fprintf(stderr, "reload %s unload: FreeLibrary failed: %lu\n", label,
                     static_cast<unsigned long>(GetLastError()));
        return false;
    }
    const HMODULE named = module_by_name(L"d3d12_xs.dll");
    const HMODULE by_entry = module_at(entry);
    if (named || by_entry) {
        std::fprintf(stderr, "reload %s unload: FreeLibrary returned TRUE but the module is still mapped "
                             "(name -> %p, export address -> %p): a reference kept it loaded\n",
                     label, static_cast<void*>(named), static_cast<void*>(by_entry));
        return false;
    }
    std::printf("reload %s unload: FreeLibrary ok, module unmapped (no module under the name, none at the export "
                "address: no reference is left)\n", label);
    return true;
}
}  // namespace

int main(int argc, char** argv) try
{
    if (argc != 2) {
        std::fputs("usage: startup_split_reload <path-to-d3d12_xs.dll>\n", stderr);
        return 2;
    }
    const std::wstring path = absolute(wide_path(argv[1]));
    if (path.empty() || GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        std::fprintf(stderr, "no d3d12_xs.dll at %ls\n", path.c_str());
        return 2;
    }
    // The harness sets the switch itself, so a manual run measures the split whether or not the test
    // environment carries it.
    SetEnvironmentVariableA("X2W_SPLIT_INDIRECT_DISPATCH", "1");
    ComPtr<ID3D12Debug> debug;
    const HRESULT debug_hr = D3D12GetDebugInterface(IID_PPV_ARGS(&debug));
    if (debug_hr != DXGI_ERROR_SDK_COMPONENT_MISSING) check(debug_hr, "get debug layer");
    if (debug) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory6> factory;
    check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "create DXGI factory");
    ComPtr<IDXGIAdapter1> adapter;
    {
        AdapterNameFilter filter;
        if (!filter.read()) return 4;
        for (UINT index = 0; factory->EnumAdapters1(index, adapter.ReleaseAndGetAddressOf()) == S_OK; ++index) {
            DXGI_ADAPTER_DESC1 desc{};
            if (SUCCEEDED(adapter->GetDesc1(&desc)) && !(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) &&
                filter.matches(desc.Description) &&
                SUCCEEDED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, __uuidof(ID3D12Device), nullptr)))
                break;
        }
        if (!adapter) return filter.no_match();
    }
    DXGI_ADAPTER_DESC1 adapter_desc{};
    check(adapter->GetDesc1(&adapter_desc), "get adapter description");
    // The same report the other GPU fixtures print, so a run names its adapter, driver, Windows build and
    // debug-layer state on its own.
    std::printf("backend=hardware adapter=%ls vendor=%04x device=%04x\n", adapter_desc.Description,
                adapter_desc.VendorId, adapter_desc.DeviceId);
    LARGE_INTEGER driver{};
    if (SUCCEEDED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &driver))) {
        std::printf("driver=%u.%u.%u.%u\n", HIWORD(driver.HighPart), LOWORD(driver.HighPart),
                    HIWORD(driver.LowPart), LOWORD(driver.LowPart));
    } else {
        std::puts("driver=unavailable via DXGI");
    }
    // GetVersionExW lies without a manifest; RtlGetVersion answers the build the run really is on.
    using RtlGetVersionFn = LONG (WINAPI*)(OSVERSIONINFOW*);
    const auto rtl_get_version = reinterpret_cast<RtlGetVersionFn>(
        GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion"));
    OSVERSIONINFOW os{};
    os.dwOSVersionInfoSize = sizeof(os);
    if (rtl_get_version && rtl_get_version(&os) == 0) {
        std::printf("windows=%lu.%lu.%lu\n", os.dwMajorVersion, os.dwMinorVersion, os.dwBuildNumber);
    } else {
        std::puts("windows=unavailable");
    }
    std::printf("debug_layer=%s\n", debug ? "enabled" : "unavailable");
    std::puts("split_indirect_dispatch=1");

    Shim first = load(path);
    if (!first.module) return 5;
    const HMODULE first_base = first.module;
    std::printf("reload phase A: module base=%p\n", static_cast<void*>(first.module));
    const bool phase_a = run_phase(first, adapter.Get(), debug != nullptr, "phase A");
    if (!unload(first, "phase A")) return 5;

    Shim second = load(path);
    if (!second.module) {
        std::fputs("reload phase B: loading d3d12_xs.dll again failed\n", stderr);
        return 5;
    }
    std::printf("reload phase B: module base=%p\n", static_cast<void*>(second.module));
    if (second.module == first_base)
        std::fputs("reload phase B: the loader reused phase A's address; the unload check above, not the address, "
                   "is the evidence that this is a distinct image\n", stdout);
    const bool phase_b = run_phase(second, adapter.Get(), debug != nullptr, "phase B");
    if (!unload(second, "phase B")) return 5;

    if (!phase_a || !phase_b) {
        std::fprintf(stderr, "%s\n", !phase_a && !phase_b
                     ? "reload: phase A and phase B did not read back the expected result word"
                     : !phase_a ? "reload: phase A did not read back the expected result word"
                                : "reload: phase B did not read back the expected result word");
        return 1;
    }
    return 0;
}
catch (const std::exception&) {
    return 3;
}
