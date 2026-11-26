cmake_minimum_required(VERSION 3.21)
project(Xbox2Windows LANGUAGES CXX)

enable_testing()

# Python never caches the bytecode of the script it is started with, so every start of a big
# tests/<name>.py recompiled it. tests/pyc_main.py <name> runs that file through the import system,
# which reuses a valid .pyc. The add_test calls below keep naming the script; this wrapper swaps in
# the entry plus the module name in one place. Other add_test calls pass through unchanged.
set(x2w_pyc_main_modules pixel_aot_check compute_store_check)
function(add_test)
  list(LENGTH ARGV x2w_test_argc)
  if(NOT x2w_test_argc EQUAL ARGC)
    message(FATAL_ERROR "add_test wrapper: an argument is empty or holds ';'; call _add_test directly")
  endif()
  set(x2w_test_args "${ARGV}")
  foreach(x2w_module IN LISTS x2w_pyc_main_modules)
    string(REPLACE "/tests/${x2w_module}.py" "/tests/pyc_main.py;${x2w_module}" x2w_test_args "${x2w_test_args}")
  endforeach()
  _add_test(${x2w_test_args})
endfunction()

# Defined before the first Python-driven test so a fresh configure registers all of them.
set(INTAKE_PYTHON "${CMAKE_SOURCE_DIR}/out/pe-env/Scripts/python.exe" CACHE FILEPATH
    "Native x64 Python with pefile for static intake tests")
if(EXISTS "${INTAKE_PYTHON}")
    add_test(NAME pyc_main_entry COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pyc_main_check.py")
    set_tests_properties(pyc_main_entry PROPERTIES TIMEOUT 60)
    add_test(NAME ci_run_checks_parallel_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/run_checks_parallel_cli_check.py")
endif()

set(DSTORAGE_SDK_ROOT "" CACHE PATH "Extracted Microsoft.Direct3D.DirectStorage NuGet package")
if(DSTORAGE_SDK_ROOT)
    find_package(ZLIB 1.2.9 REQUIRED)
    set(dstorage_native "${DSTORAGE_SDK_ROOT}/native")
    add_executable(dstorage_rfc1950_check tests/dstorage_rfc1950_check.cpp src/dstorage_rfc1950.cpp)
    target_compile_features(dstorage_rfc1950_check PRIVATE cxx_std_17)
    target_include_directories(dstorage_rfc1950_check PRIVATE src "${dstorage_native}/include")
    target_link_libraries(dstorage_rfc1950_check PRIVATE "${dstorage_native}/lib/x64/dstorage.lib" ZLIB::ZLIB)
    add_custom_command(TARGET dstorage_rfc1950_check POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different "${dstorage_native}/bin/x64/dstorage.dll"
            "${dstorage_native}/bin/x64/dstoragecore.dll" "$<TARGET_FILE_DIR:dstorage_rfc1950_check>"
        VERBATIM)
    foreach(scenario IN ITEMS success truncated checksum trailing oversize undersize refusals)
        add_test(NAME dstorage_rfc1950_${scenario} COMMAND dstorage_rfc1950_check ${scenario})
        set_tests_properties(dstorage_rfc1950_${scenario} PROPERTIES TIMEOUT 30)
    endforeach()
    # Negative control for the refusals case: a build-tree copy of the adapter without the 32-bit
    # bound on SrcSize. The check must report that request as decoded instead of refused.
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS src/dstorage_rfc1950.cpp)
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/dstorage_rfc1950.cpp" dstorage_rfc1950_text)
    string(REPLACE "request.SrcSize > ULONG_MAX || " "" dstorage_rfc1950_control_text "${dstorage_rfc1950_text}")
    if(dstorage_rfc1950_control_text STREQUAL dstorage_rfc1950_text)
        message(FATAL_ERROR "dstorage_rfc1950.cpp lost the anchor used by dstorage_rfc1950_refusals_truncation_control")
    endif()
    set(dstorage_rfc1950_control "${CMAKE_CURRENT_BINARY_DIR}/dstorage_rfc1950_control/dstorage_rfc1950.cpp")
    file(WRITE "${dstorage_rfc1950_control}" "${dstorage_rfc1950_control_text}")
    add_executable(dstorage_rfc1950_truncation_control tests/dstorage_rfc1950_check.cpp "${dstorage_rfc1950_control}")
    target_compile_features(dstorage_rfc1950_truncation_control PRIVATE cxx_std_17)
    target_include_directories(dstorage_rfc1950_truncation_control PRIVATE src "${dstorage_native}/include")
    target_link_libraries(dstorage_rfc1950_truncation_control PRIVATE "${dstorage_native}/lib/x64/dstorage.lib" ZLIB::ZLIB)
    add_custom_command(TARGET dstorage_rfc1950_truncation_control POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different "${dstorage_native}/bin/x64/dstorage.dll"
            "${dstorage_native}/bin/x64/dstoragecore.dll" "$<TARGET_FILE_DIR:dstorage_rfc1950_truncation_control>"
        VERBATIM)
    add_test(NAME dstorage_rfc1950_refusals_truncation_control COMMAND dstorage_rfc1950_truncation_control refusals)
    set_tests_properties(dstorage_rfc1950_refusals_truncation_control PROPERTIES TIMEOUT 30
        PASS_REGULAR_EXPRESSION "FAIL: refusals src_over_ulong_max: status 0x8007000d")
endif()
add_executable(guest_content_root_check tests/guest_content_root_check.cpp)
target_compile_features(guest_content_root_check PRIVATE cxx_std_17)
add_test(NAME startup_content_root COMMAND guest_content_root_check "${CMAKE_CURRENT_BINARY_DIR}")
set_tests_properties(startup_content_root PROPERTIES SKIP_RETURN_CODE 77)

add_executable(root_probe tools/root_probe.cpp)
target_compile_features(root_probe PRIVATE cxx_std_17)
target_link_libraries(root_probe PRIVATE d3d12)
add_executable(root_device_probe tools/root_device_probe.cpp)
target_compile_features(root_device_probe PRIVATE cxx_std_17)
target_link_libraries(root_device_probe PRIVATE d3d12 dxgi)
add_executable(d3d12_sdk_check tests/d3d12_sdk_check.cpp)
target_compile_features(d3d12_sdk_check PRIVATE cxx_std_17)
target_link_libraries(d3d12_sdk_check PRIVATE d3d12)
add_test(NAME desktop_root_signature COMMAND d3d12_sdk_check)
add_test(NAME desktop_bvh_root_flags COMMAND d3d12_sdk_check bvh-flags)

add_executable(era_heap_check tests/era_heap_check.cpp src/era_heap.cpp)
target_include_directories(era_heap_check PRIVATE src)
target_compile_features(era_heap_check PRIVATE cxx_std_20)
foreach(scenario IN ITEMS allocation failure concurrency caller_layout reuse observed_words large_alignment graphics_types
        decode_fields)
    add_test(NAME era_heap_${scenario} COMMAND era_heap_check ${scenario})
endforeach()
# Negative control: expects a 13-bit object type, so the widest object type must make it fail.
add_test(NAME era_heap_decode_fields_control COMMAND era_heap_check decode_fields_control)
set_tests_properties(era_heap_decode_fields_control PROPERTIES WILL_FAIL TRUE)

add_executable(memory_query_check tests/memory_query_check.cpp)
target_compile_features(memory_query_check PRIVATE cxx_std_17)
target_link_libraries(memory_query_check PRIVATE psapi)
add_test(NAME desktop_memory_query COMMAND memory_query_check)

# tracy_new.cpp against a recording stand-in for Tracy's memory macros (no Tracy fetched, runs in every build).
add_executable(tracy_new_check tests/tracy_new_check.cpp)
target_compile_features(tracy_new_check PRIVATE cxx_std_17)
target_include_directories(tracy_new_check PRIVATE tests/fixtures/tracy_fake)
target_compile_definitions(tracy_new_check PRIVATE X2W_TRACY=1 X2W_TRACY_HEAP="test C++ heap")
add_test(NAME tracy_new COMMAND tracy_new_check)

add_executable(xmem_committed_memory_check tests/xmem_committed_memory_check.cpp)
target_compile_features(xmem_committed_memory_check PRIVATE cxx_std_17)
target_link_libraries(xmem_committed_memory_check PRIVATE OneCore)
add_test(NAME xmem_committed_memory COMMAND xmem_committed_memory_check)

add_executable(era_query_check tests/era_query_check.cpp src/era_query.cpp)
target_include_directories(era_query_check PRIVATE src)
target_compile_features(era_query_check PRIVATE cxx_std_17)
foreach(scenario IN ITEMS fields tail registry short)
    add_test(NAME era_query_${scenario} COMMAND era_query_check ${scenario})
endforeach()
# A clear tail flag overwrites a stale byte, and another process's page at a registered address
# has it clear. The mutated run, which expects the flag set there, is the negative control.
add_test(NAME era_query_clear COMMAND era_query_check clear)
add_test(NAME era_query_clear_foreign_control COMMAND era_query_check clear --mutate foreign)
set_tests_properties(era_query_clear_foreign_control PROPERTIES WILL_FAIL TRUE)

# Title GPU address to desktop GPU virtual address table (no GPU needed).
add_executable(era_title_va_check tests/era_title_va_check.cpp src/era_title_va.cpp)
target_include_directories(era_title_va_check PRIVATE src)
target_compile_features(era_title_va_check PRIVATE cxx_std_17)
foreach(scenario IN ITEMS translate bounds registry shader)
    add_test(NAME era_title_va_${scenario} COMMAND era_title_va_check ${scenario})
endforeach()

# era_title_gpu under allocation failure (no GPU needed). The program replaces operator new to fail
# one chosen allocation at a time.
add_executable(era_title_gpu_alloc_check tests/era_title_gpu_alloc_check.cpp src/era_title_gpu.cpp
    src/era_gpu_alias.cpp src/era_title_va.cpp src/era_query.cpp)
target_include_directories(era_title_gpu_alloc_check PRIVATE src)
target_compile_features(era_title_gpu_alloc_check PRIVATE cxx_std_20)
add_test(NAME era_title_gpu_alloc COMMAND era_title_gpu_alloc_check)
set_tests_properties(era_title_gpu_alloc PROPERTIES TIMEOUT 30)

# Physical-page bookkeeping behind XMemAllocatePhysicalPages/XMemFreePhysicalPages, linked next to a
# lenient build of the same file (ERA_PHYSICAL_LENIENT_RELEASE) that the ownership controls must catch.
add_library(era_physical_lenient OBJECT src/era_physical.cpp)
target_include_directories(era_physical_lenient PRIVATE src)
target_compile_features(era_physical_lenient PRIVATE cxx_std_17)
target_compile_definitions(era_physical_lenient PRIVATE ERA_PHYSICAL_LENIENT_RELEASE era_physical=era_physical_lenient)
add_executable(era_physical_check tests/era_physical_check.cpp src/era_physical.cpp $<TARGET_OBJECTS:era_physical_lenient>)
target_include_directories(era_physical_check PRIVATE src)
target_compile_features(era_physical_check PRIVATE cxx_std_17)
foreach(scenario IN ITEMS controls lifetime owns)
    add_test(NAME era_physical_${scenario} COMMAND era_physical_check ${scenario})
endforeach()
# Control for era_physical_owns: the same check built against a configure-time copy of
# era_physical.cpp whose owns() refuses the last page number, which the full registry must catch.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS src/era_physical.cpp)
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/era_physical.cpp" era_physical_text)
string(FIND "${era_physical_text}" "return page && page <= capacity_pages && " era_physical_anchor)
if(era_physical_anchor LESS 0)
    message(FATAL_ERROR "era_physical.cpp lost the anchor used by era_physical_owns_last_page_control")
endif()
string(REPLACE "return page && page <= capacity_pages && " "return page && page < capacity_pages && "
    era_physical_text "${era_physical_text}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/era_physical_last_page/era_physical.cpp" "${era_physical_text}")
add_executable(era_physical_last_page_check tests/era_physical_check.cpp
    "${CMAKE_CURRENT_BINARY_DIR}/era_physical_last_page/era_physical.cpp" $<TARGET_OBJECTS:era_physical_lenient>)
target_include_directories(era_physical_last_page_check PRIVATE src)
target_compile_features(era_physical_last_page_check PRIVATE cxx_std_17)
add_test(NAME era_physical_owns_last_page_control COMMAND era_physical_last_page_check owns)
set_tests_properties(era_physical_owns_last_page_control PROPERTIES PASS_REGULAR_EXPRESSION
    "FAIL: owns: last page")

# Desktop xmem.dll for native and mapped callers.
add_library(xmem_shim SHARED src/xmem_shim.cpp src/xmem_shim.def src/xmem_gpu_usage.cpp src/adapter_identity.cpp src/era_heap.cpp src/era_query.cpp src/era_physical.cpp
    src/era_title_gpu.cpp src/era_gpu_alias.cpp src/era_title_va.cpp src/xmem_mapped_pages.cpp)
set_target_properties(xmem_shim PROPERTIES OUTPUT_NAME xmem)
# LINK uses explicit export ordinals in the generated import library. Keep
# those ordinals in the DLL and build the consumer library with names.
set(xmem_export_def "${CMAKE_CURRENT_SOURCE_DIR}/src/xmem_shim.def")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${xmem_export_def}")
file(READ "${xmem_export_def}" xmem_named_exports)
string(REGEX REPLACE "(=[A-Za-z0-9_]+)? +@[0-9]+" "" xmem_named_exports "${xmem_named_exports}")
set(xmem_named_def "${CMAKE_CURRENT_BINARY_DIR}/xmem_named_imports.def")
file(GENERATE OUTPUT "${xmem_named_def}" CONTENT "${xmem_named_exports}")
set_property(TARGET xmem_shim APPEND PROPERTY LINK_DEPENDS "${xmem_named_def}")
add_custom_command(TARGET xmem_shim POST_BUILD
    COMMAND "${CMAKE_AR}" /nologo /machine:x64 "/def:${xmem_named_def}" "/out:$<TARGET_LINKER_FILE:xmem_shim>"
    VERBATIM)
target_include_directories(xmem_shim PRIVATE src)
target_compile_features(xmem_shim PRIVATE cxx_std_20)
# Delay-loaded: only XMemGetWorkingSetStatistics uses DXGI and D3DKMT (gdi32).
target_link_libraries(xmem_shim PRIVATE dxgi gdi32 delayimp OneCore)
target_link_options(xmem_shim PRIVATE /DELAYLOAD:dxgi.dll /DELAYLOAD:gdi32.dll)
# The same shim with its test controls compiled in (X2W_XMEM_TEST_CONTROLS): refusing one step of an
# unmap, and shared views without the fault handler. tests/xmem_page_runs_check.py loads it for the
# cases that need a control; the deployed xmem.dll has neither switch.
get_target_property(xmem_shim_sources xmem_shim SOURCES)
add_library(xmem_shim_test_controls SHARED ${xmem_shim_sources})
set_target_properties(xmem_shim_test_controls PROPERTIES OUTPUT_NAME xmem
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/xmem-test-controls"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/xmem-test-controls"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/xmem-test-controls"
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
target_compile_definitions(xmem_shim_test_controls PRIVATE X2W_XMEM_TEST_CONTROLS)
target_include_directories(xmem_shim_test_controls PRIVATE src)
target_compile_features(xmem_shim_test_controls PRIVATE cxx_std_20)
target_link_libraries(xmem_shim_test_controls PRIVATE dxgi gdi32 delayimp OneCore)
target_link_options(xmem_shim_test_controls PRIVATE /DELAYLOAD:dxgi.dll /DELAYLOAD:gdi32.dll)
add_executable(xmem_shim_check tests/xmem_shim_check.cpp src/adapter_identity.cpp)
# D3D12 and DXGI are delay-loaded so the exports scenario can check that xmem.dll loads neither.
target_link_libraries(xmem_shim_check PRIVATE xmem_shim d3d12 dxgi gdi32 delayimp)
target_link_options(xmem_shim_check PRIVATE /DELAYLOAD:d3d12.dll /DELAYLOAD:dxgi.dll)
target_include_directories(xmem_shim_check PRIVATE src)
target_compile_features(xmem_shim_check PRIVATE cxx_std_17)
# working_set_aggregation feeds synthetic adapter readings to src/xmem_gpu_usage.h.
foreach(scenario IN ITEMS exports allocation default_allocation physical_pages tools_memory transfer_memory query working_set working_set_aggregation)
    add_test(NAME xmem_shim_${scenario} COMMAND xmem_shim_check ${scenario})
endforeach()
# XMemGetWorkingSetStatistics differences around D3D12 heap and committed-resource lifetimes.
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME xmem_shim_working_set_${adapter} COMMAND xmem_shim_check working_set_${adapter})
    set_tests_properties(xmem_shim_working_set_${adapter} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
endforeach()

# Second commit/protection check (#870): ordinary committed pages vs live shared-page views.
add_executable(xmem_commit_protection_check tests/xmem_commit_protection_check.cpp)
target_link_libraries(xmem_commit_protection_check PRIVATE xmem_shim OneCore)
target_include_directories(xmem_commit_protection_check PRIVATE src)
target_compile_features(xmem_commit_protection_check PRIVATE cxx_std_20)
add_test(NAME xmem_commit_protection COMMAND xmem_commit_protection_check)
set_tests_properties(xmem_commit_protection PROPERTIES TIMEOUT 30)

# Slab slot bookkeeping of the physical pages (#1199): standard C++17 only, no Windows calls.
add_executable(xmem_slab_slots_check tests/xmem_slab_slots_check.cpp)
target_include_directories(xmem_slab_slots_check PRIVATE src)
target_compile_features(xmem_slab_slots_check PRIVATE cxx_std_17)
add_test(NAME xmem_slab_slots COMMAND xmem_slab_slots_check)
set_tests_properties(xmem_slab_slots PROPERTIES TIMEOUT 30)
if(EXISTS "${INTAKE_PYTHON}")
    # Startup memory accounting (#1199): the live physical-page section snapshot, and the peak commit
    # and section count the DirectStorage heartbeat reports from it.
    add_test(NAME xmem_page_stats COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_page_stats_check.py" "$<TARGET_FILE:xmem_shim>")
    # A page-token write names granted pages only: no section outside a grant, and a fresh grant reads zero.
    add_test(NAME xmem_physical_write_owner COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_physical_write_owner_check.py" "$<TARGET_FILE:xmem_shim>")
    set_tests_properties(xmem_physical_write_owner PROPERTIES TIMEOUT 120)
    # A few mapped pages commit about those pages, not the whole 256 MiB slab that holds them (#1199).
    add_test(NAME xmem_mapped_pages_commit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_mapped_pages_commit_check.py" "$<TARGET_FILE:xmem_shim>")
    add_test(NAME xmem_mapped_pages_commit_failure COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_mapped_pages_commit_check.py" "$<TARGET_FILE:xmem_shim_test_controls>" failure)
    set_tests_properties(xmem_mapped_pages_commit xmem_mapped_pages_commit_failure PROPERTIES TIMEOUT 60 RUN_SERIAL TRUE)
    set_tests_properties(xmem_mapped_pages_commit_failure PROPERTIES ENVIRONMENT "X2W_XMEM_TEST_COMMIT_FAILURE=1")
    # X2W_XMEM_LAZY_COMMIT=1: pages committed on first touch; kernel writes need x2w_xmem_commit_range (#1199).
    add_test(NAME xmem_lazy_commit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_lazy_commit_check.py" "$<TARGET_FILE:xmem_shim>")
    set_tests_properties(xmem_lazy_commit PROPERTIES TIMEOUT 60 RUN_SERIAL TRUE ENVIRONMENT "X2W_XMEM_LAZY_COMMIT=1")
    # Control: with the switch off, mapping commits every page as before.
    add_test(NAME xmem_lazy_commit_off COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_lazy_commit_check.py" "$<TARGET_FILE:xmem_shim>" off)
    set_tests_properties(xmem_lazy_commit_off PROPERTIES TIMEOUT 60 RUN_SERIAL TRUE ENVIRONMENT "X2W_XMEM_LAZY_COMMIT=0")
    add_test(NAME xmem_lazy_startup COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_lazy_startup_check.py" "$<TARGET_FILE:xmem_shim>")
    set_tests_properties(xmem_lazy_startup PROPERTIES TIMEOUT 60 RUN_SERIAL TRUE
        ENVIRONMENT "X2W_XMEM_LAZY_COMMIT=1;X2W_XMEM_LAZY_STARTUP=1")
    # Control: with X2W_XMEM_LAZY_STARTUP off, the startup blocks are committed as before.
    add_test(NAME xmem_lazy_startup_off COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_lazy_startup_check.py" "$<TARGET_FILE:xmem_shim>" off)
    set_tests_properties(xmem_lazy_startup_off PROPERTIES TIMEOUT 60
        ENVIRONMENT "X2W_XMEM_LAZY_COMMIT=1;X2W_XMEM_LAZY_STARTUP=0")
    add_test(NAME startup_heartbeat_commit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_heartbeat_check.py"
        "$<TARGET_FILE:xmem_shim>" "$<TARGET_FILE:startup_stub_xcrdapi>")
    set_tests_properties(startup_heartbeat_commit PROPERTIES TIMEOUT 60)
    # Startup tooling lint (#1149): every Python file under tools/startup must parse. The check compiles each
    # source without running it and self-tests that a broken snippet is rejected, so a passing run means the
    # files were actually looked at. It needs no GPU and no game files.
    add_test(NAME startup_shader_cache_key COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_shader_cache_key_check.py")
    set_tests_properties(startup_shader_cache_key PROPERTIES TIMEOUT 30)
    add_test(NAME startup_tools_lint COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_tools_lint_check.py" "${CMAKE_SOURCE_DIR}/tools/startup")
    set_tests_properties(startup_tools_lint PROPERTIES TIMEOUT 60)
endif()
# Mutation controls: each run flips one expected value and passes only when the
# named check reports it. An unknown mutation name or an overall PASS fails.
foreach(mutation_and_check
        "xva_positive_refused|check_failed: xva_accepted_pair"
        "xva_commit_accepted|check_failed: xva_commit_bit"
        "xva_readonly_accepted|check_failed: xva_protection"
        "xva_state_dependent|check_failed: xva_address_state_independent"
        "private_second_va_aliases|check_failed: private_second_va_independent.*failing_fields=private_second_va\n"
        "private_type_mapped|check_failed: private_type.*failing_fields=private_type\n"
        "mapped_decommit_succeeds|check_failed: mapped_decommit.*failing_fields=mapped_decommit\n")
  string(FIND "${mutation_and_check}" "|" split)
  string(SUBSTRING "${mutation_and_check}" 0 ${split} mutation)
  math(EXPR expected_start "${split} + 1")
  string(SUBSTRING "${mutation_and_check}" ${expected_start} -1 expected_output)
  add_test(NAME xmem_commit_protection_mutate_${mutation}
           COMMAND xmem_commit_protection_check --mutate ${mutation})
  set_tests_properties(xmem_commit_protection_mutate_${mutation} PROPERTIES
    TIMEOUT 30
    PASS_REGULAR_EXPRESSION "${expected_output}"
    FAIL_REGULAR_EXPRESSION "unknown mutation|xmem_commit_protection: PASS")
endforeach()

# Startup blocks below 2^40 (#1758, under #874): X2W_XMEM_STARTUP_BELOW_40=1 places the 0x283 large-page
# startup blocks entirely below 2^40 or refuses them. The check loads xmem.dll by path; the deployed
# shim must ignore the test-build mutants, and each mutant in the test-controls build must make the
# named check fail.
# The import wrappers of X2W_XMEM_LAZY_COMMIT / X2W_XMEM_LAZY_STARTUP (#1199): ReadFile and VirtualFree of the
# main module, which the Python checks cannot reach.
add_executable(xmem_lazy_imports_check tests/xmem_lazy_imports_check.cpp)
target_compile_features(xmem_lazy_imports_check PRIVATE cxx_std_17)
add_dependencies(xmem_lazy_imports_check xmem_shim xmem_shim_test_controls)
add_test(NAME xmem_lazy_imports COMMAND xmem_lazy_imports_check "$<TARGET_FILE:xmem_shim>")
set_tests_properties(xmem_lazy_imports PROPERTIES TIMEOUT 60)
# A refused fault handler (test-controls build) leaves the switches off: pages and blocks are committed up front.
add_test(NAME xmem_lazy_handler_failure COMMAND xmem_lazy_imports_check
    "$<TARGET_FILE:xmem_shim_test_controls>" handler-failure)
set_tests_properties(xmem_lazy_handler_failure PROPERTIES TIMEOUT 60)
add_executable(xmem_section_lease_check tests/xmem_section_lease_check.cpp tests/desktop_gpu.cpp)
target_include_directories(xmem_section_lease_check PRIVATE src)
target_compile_features(xmem_section_lease_check PRIVATE cxx_std_17)
target_link_libraries(xmem_section_lease_check PRIVATE d3d12 dxgi)
add_dependencies(xmem_section_lease_check xmem_shim)
add_test(NAME xmem_section_lease_single_page COMMAND xmem_section_lease_check single-page "$<TARGET_FILE:xmem_shim>")
foreach(adapter warp hardware)
  add_test(NAME xmem_section_lease_${adapter} COMMAND xmem_section_lease_check ${adapter} "$<TARGET_FILE:xmem_shim>")
  set_tests_properties(xmem_section_lease_${adapter} PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
  add_test(NAME xmem_page_batch_inflight_${adapter} COMMAND xmem_section_lease_check ${adapter} "$<TARGET_FILE:xmem_shim>" page-batch)
  set_tests_properties(xmem_page_batch_inflight_${adapter} PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
  add_test(NAME xmem_section_lease_mesh_${adapter} COMMAND xmem_section_lease_check ${adapter} "$<TARGET_FILE:xmem_shim>" mesh)
  add_test(NAME xmem_section_lease_vertex_${adapter} COMMAND xmem_section_lease_check ${adapter} "$<TARGET_FILE:xmem_shim>" vertex)
  set_tests_properties(xmem_section_lease_vertex_${adapter} xmem_section_lease_mesh_${adapter} PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
endforeach()
add_executable(xmem_startup_below_40_check tests/xmem_startup_below_40_check.cpp)
target_link_libraries(xmem_startup_below_40_check PRIVATE OneCore)
target_compile_features(xmem_startup_below_40_check PRIVATE cxx_std_17)
add_dependencies(xmem_startup_below_40_check xmem_shim xmem_shim_test_controls)
add_test(NAME xmem_startup_below_40 COMMAND xmem_startup_below_40_check "$<TARGET_FILE:xmem_shim>")
add_test(NAME xmem_startup_below_40_deployed_ignores_mutants
         COMMAND xmem_startup_below_40_check "$<TARGET_FILE:xmem_shim>")
set_tests_properties(xmem_startup_below_40 xmem_startup_below_40_deployed_ignores_mutants PROPERTIES
    TIMEOUT 60 PASS_REGULAR_EXPRESSION "xmem_startup_below_40: PASS")
set_tests_properties(xmem_startup_below_40_deployed_ignores_mutants PROPERTIES
    ENVIRONMENT "X2W_XMEM_TEST_BELOW_40=no_limit+no_check+no_release")
# Each entry: mutant @ output that must appear @ output that must not. Without the limit the check
# after the allocation still refuses and releases the high block (no NULL or leak failure); without
# the check the high block is returned; without the release it stays allocated.
foreach(entry
        "no_limit@check_failed: exhausted_host_refusal@xmem_startup_below_40: PASS|check_failed: exhausted_(null|no_leak)"
        "no_limit+no_check@check_failed: exhausted_null@xmem_startup_below_40: PASS"
        "no_limit+no_release@check_failed: exhausted_no_leak@xmem_startup_below_40: PASS|check_failed: exhausted_null")
  string(REPLACE "@" ";" fields "${entry}")
  list(GET fields 0 mutant)
  list(GET fields 1 expected_output)
  list(GET fields 2 forbidden_output)
  string(REPLACE "+" "_" mutant_name "${mutant}")
  add_test(NAME xmem_startup_below_40_mutant_${mutant_name}
           COMMAND xmem_startup_below_40_check "$<TARGET_FILE:xmem_shim_test_controls>")
  set_tests_properties(xmem_startup_below_40_mutant_${mutant_name} PROPERTIES
    TIMEOUT 60
    ENVIRONMENT "X2W_XMEM_TEST_BELOW_40=${mutant}"
    PASS_REGULAR_EXPRESSION "${expected_output}"
    FAIL_REGULAR_EXPRESSION "${forbidden_output}")
endforeach()

add_executable(windows_placeholder_partition_check tests/windows_placeholder_partition_check.cpp)
target_compile_features(windows_placeholder_partition_check PRIVATE cxx_std_17)
target_link_libraries(windows_placeholder_partition_check PRIVATE OneCore)
add_test(NAME windows_placeholder_partition COMMAND windows_placeholder_partition_check)

# Source revision for the presenter window title and the device-create log line (src/x2w_build_rev.h).
# The generator runs on every build and rewrites the small generated source only when the revision
# changes, so a new commit recompiles that file alone. /Zl: the library is linked into targets with
# either CRT, so its object names none.
find_package(Git QUIET)
set(x2w_build_rev_source "${CMAKE_CURRENT_BINARY_DIR}/generated/x2w_build_rev.cpp")
add_custom_target(x2w_build_rev_generate
    COMMAND "${CMAKE_COMMAND}" "-DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}" "-DOUTPUT=${x2w_build_rev_source}"
        "-DGIT_EXECUTABLE=${GIT_EXECUTABLE}" -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/x2w_build_rev.cmake"
    BYPRODUCTS "${x2w_build_rev_source}"
    VERBATIM)
add_library(x2w_build_rev STATIC "${x2w_build_rev_source}")
add_dependencies(x2w_build_rev x2w_build_rev_generate)
target_include_directories(x2w_build_rev PRIVATE src)
target_compile_options(x2w_build_rev PRIVATE /Zl)

# Desktop d3d12_xs.dll for the package DLLs' two named d3d12_xs root-signature imports.
add_library(d3d12_xs_shim SHARED src/d3d12_xs_shim.cpp src/d3d12x_device_slots.cpp
    src/d3d12_xs_iids.cpp src/d3d12_xs_shim.def src/startup_stubs/d3d12_xs_device.cpp)
set_target_properties(d3d12_xs_shim PROPERTIES OUTPUT_NAME d3d12_xs)
target_include_directories(d3d12_xs_shim PRIVATE src)
target_compile_features(d3d12_xs_shim PRIVATE cxx_std_17)
target_link_libraries(d3d12_xs_shim PRIVATE d3d12)
# The creation-IID gate and refusal text of D3D12XboxCreateDevice (src/d3d12x_device_slots.h),
# without a device. The mutated run is the negative control.
add_executable(d3d12x_device_slots_check tests/d3d12x_device_slots_check.cpp src/d3d12x_device_slots.cpp)
target_include_directories(d3d12x_device_slots_check PRIVATE src)
target_compile_features(d3d12x_device_slots_check PRIVATE cxx_std_17)
add_test(NAME d3d12x_device_slots COMMAND d3d12x_device_slots_check)
add_test(NAME d3d12x_device_slots_device1_control COMMAND d3d12x_device_slots_check --mutate device1)
set_tests_properties(d3d12x_device_slots_device1_control PROPERTIES WILL_FAIL TRUE)

# Fixture-only desktop xgameruntime.dll. The single X-macro table in
# xgameruntime_shim.cpp distinguishes implemented contracts and the manual-queue async
# operations. Keep it out of the normal shim directory so a package
# cannot treat the production-named DLL as a provider.
add_library(xgameruntime_shim SHARED src/xgameruntime_shim.cpp src/xgameruntime_shim.def)
set(xgameruntime_fixture_dir "${CMAKE_BINARY_DIR}/fixture-shims")
set_target_properties(xgameruntime_shim PROPERTIES
    OUTPUT_NAME xgameruntime
    RUNTIME_OUTPUT_DIRECTORY "${xgameruntime_fixture_dir}"
    LIBRARY_OUTPUT_DIRECTORY "${xgameruntime_fixture_dir}"
    ARCHIVE_OUTPUT_DIRECTORY "${xgameruntime_fixture_dir}")
target_compile_features(xgameruntime_shim PRIVATE cxx_std_17)

add_executable(xgameruntime_shim_check tests/xgameruntime_thunks_check.cpp)
add_dependencies(xgameruntime_shim_check xgameruntime_shim)
target_compile_features(xgameruntime_shim_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_thunks COMMAND xgameruntime_shim_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
# These three tests use the fixed %TEMP%\xbox-recomp-pls and %TEMP%\xbox-recomp-packages directories,
# so they must not overlap when CTest runs tests in parallel.
set_tests_properties(xgameruntime_thunks PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_contracts_check tests/xgameruntime_contracts_check.cpp)
target_link_libraries(xgameruntime_contracts_check PRIVATE xgameruntime_shim)
target_compile_features(xgameruntime_contracts_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_contracts COMMAND xgameruntime_contracts_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
set_tests_properties(xgameruntime_contracts PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_gamesave_async_check tests/xgameruntime_gamesave_async_check.cpp)
add_dependencies(xgameruntime_gamesave_async_check xgameruntime_shim)
target_compile_features(xgameruntime_gamesave_async_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_gamesave_async COMMAND xgameruntime_gamesave_async_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
set_tests_properties(xgameruntime_gamesave_async PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_gamesave_enumerate_check tests/xgameruntime_gamesave_enumerate_check.cpp)
add_dependencies(xgameruntime_gamesave_enumerate_check xgameruntime_shim)
target_compile_features(xgameruntime_gamesave_enumerate_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_gamesave_enumerate COMMAND xgameruntime_gamesave_enumerate_check
    "$<TARGET_FILE:xgameruntime_shim>")
set_tests_properties(xgameruntime_gamesave_enumerate PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_async_status_check tests/xgameruntime_async_status_check.cpp)
add_dependencies(xgameruntime_async_status_check xgameruntime_shim)
target_compile_features(xgameruntime_async_status_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_async_status COMMAND xgameruntime_async_status_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
set_tests_properties(xgameruntime_async_status PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_user_async_check tests/xgameruntime_user_async_check.cpp)
add_dependencies(xgameruntime_user_async_check xgameruntime_shim)
target_compile_features(xgameruntime_user_async_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_user_async COMMAND xgameruntime_user_async_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
set_tests_properties(xgameruntime_user_async PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_package_async_check tests/xgameruntime_package_async_check.cpp)
add_dependencies(xgameruntime_package_async_check xgameruntime_shim)
target_compile_features(xgameruntime_package_async_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_package_async COMMAND xgameruntime_package_async_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
set_tests_properties(xgameruntime_package_async PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_pls_xpackage_check tests/xgameruntime_pls_xpackage_check.cpp)
add_dependencies(xgameruntime_pls_xpackage_check xgameruntime_shim)
target_compile_features(xgameruntime_pls_xpackage_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_pls_xpackage COMMAND xgameruntime_pls_xpackage_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
set_tests_properties(xgameruntime_pls_xpackage PROPERTIES TIMEOUT 30 RESOURCE_LOCK xgameruntime_temp_directories)

add_executable(xgameruntime_identity_check tests/xgameruntime_identity_check.cpp)
add_dependencies(xgameruntime_identity_check xgameruntime_shim)
target_compile_features(xgameruntime_identity_check PRIVATE cxx_std_17)
add_test(NAME xgameruntime_identity COMMAND xgameruntime_identity_check
    "$<TARGET_FILE:xgameruntime_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
    "$<TARGET_FILE_DIR:xmem_shim>")
set_tests_properties(xgameruntime_identity PROPERTIES TIMEOUT 30)

# A real source-built EXE import fixture. The import library below only names
# xgameruntime.dll; no build product or test package copies the fixture DLL.
set(xgameruntime_import_def "${CMAKE_CURRENT_SOURCE_DIR}/tests/xgameruntime_import.def")
set(xgameruntime_import_lib "${CMAKE_CURRENT_BINARY_DIR}/xgameruntime_fixture_import.lib")
add_custom_command(OUTPUT "${xgameruntime_import_lib}"
    COMMAND "${CMAKE_AR}" /nologo /machine:x64 "/def:${xgameruntime_import_def}"
            "/out:${xgameruntime_import_lib}"
    DEPENDS tests/xgameruntime_import.def VERBATIM)
add_executable(xgameruntime_preflight_exe tests/xgameruntime_preflight_exe.cpp)
target_sources(xgameruntime_preflight_exe PRIVATE "${xgameruntime_import_lib}")
target_link_libraries(xgameruntime_preflight_exe PRIVATE "${xgameruntime_import_lib}")
target_compile_features(xgameruntime_preflight_exe PRIVATE cxx_std_17)
target_compile_options(xgameruntime_preflight_exe PRIVATE /GS-)
target_link_options(xgameruntime_preflight_exe PRIVATE /ENTRY:fixture_entry /NODEFAULTLIB
    /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)

# pe_run_package --trap-callable fixtures. The import library only names trap_fixture.dll;
# nothing builds or copies a DLL under that name. The _data variant adds a data import.
set(trap_missing_import_def "${CMAKE_CURRENT_SOURCE_DIR}/tests/trap_missing_import.def")
set(trap_missing_import_lib "${CMAKE_CURRENT_BINARY_DIR}/trap_missing_fixture_import.lib")
add_custom_command(OUTPUT "${trap_missing_import_lib}"
    COMMAND "${CMAKE_AR}" /nologo /machine:x64 "/def:${trap_missing_import_def}"
            "/out:${trap_missing_import_lib}"
    DEPENDS tests/trap_missing_import.def VERBATIM)
foreach(target IN ITEMS trap_missing_exe trap_missing_data_exe)
    add_executable(${target} tests/trap_missing_exe.cpp)
    target_sources(${target} PRIVATE "${trap_missing_import_lib}")
    target_link_libraries(${target} PRIVATE "${trap_missing_import_lib}" kernel32)
    target_compile_options(${target} PRIVATE /GS-)
    target_link_options(${target} PRIVATE /ENTRY:fixture_entry /NODEFAULTLIB
        /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
endforeach()
target_compile_definitions(trap_missing_data_exe PRIVATE TRAP_DATA_IMPORT)

# Experimental startup stand-ins (docs/startup-runtime.md): trap-by-default desktop DLLs for imports
# without a public ABI yet (src/startup_stubs/trap.h), plus opt-in permissive paths for startup runs.
set(startup_stub_targets)
foreach(stub IN ITEMS acphal:AcpHal chad:chad xapu:xapu xcrdapi:XCRDAPI xg_xs:xg_xs gameinput:GameInput)
    string(REPLACE ":" ";" stub_parts "${stub}")
    list(GET stub_parts 0 stub_stem)
    list(GET stub_parts 1 stub_output)
    add_library(startup_stub_${stub_stem} SHARED src/startup_stubs/${stub_stem}.cpp src/startup_stubs/${stub_stem}.def)
    set_target_properties(startup_stub_${stub_stem} PROPERTIES OUTPUT_NAME ${stub_output})
    target_include_directories(startup_stub_${stub_stem} PRIVATE src)
    target_compile_features(startup_stub_${stub_stem} PRIVATE cxx_std_17)
    list(APPEND startup_stub_targets startup_stub_${stub_stem})
endforeach()
# A package may ship an older MSVCP140.dll that the loader picks from the application directory;
# link the shims statically so they never use its runtime (constexpr std::mutex layout).
target_link_libraries(startup_stub_xg_xs PRIVATE d3d12 dxguid)
target_link_libraries(startup_stub_gameinput PRIVATE user32 psapi)
target_link_libraries(startup_stub_xapu PRIVATE winmm)
# Optional XApu packet decoding (docs/startup-runtime.md). Off by default: the default configure and CI
# do not need libopus. When on, find_package(Opus) must find an installed libopus built with the static
# MSVC runtime, because the stand-ins link it statically. Tested with libopus 1.5.2.
option(X2W_WITH_OPUS "Decode XApu Opus packets with an installed libopus" OFF)
if(X2W_WITH_OPUS)
    find_package(Opus CONFIG REQUIRED)
    target_link_libraries(startup_stub_xapu PRIVATE Opus::opus)
    target_compile_definitions(startup_stub_xapu PRIVATE X2W_HAVE_OPUS=1)
endif()
# The DirectStorage heartbeat reports this process's peak commit (#1199).
target_link_libraries(startup_stub_xcrdapi PRIVATE psapi)
target_sources(startup_stub_gameinput PRIVATE src/startup_stubs/runtime_proxy.cpp)
target_link_libraries(d3d12_xs_shim PRIVATE user32 gdi32 d3dcompiler dxgi x2w_build_rev)
target_compile_options(d3d12_xs_shim PRIVATE /bigobj)
set_target_properties(xmem_shim d3d12_xs_shim ${startup_stub_targets} PROPERTIES
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
# Developer-only measurement build: Tracy zones and memory pools in the stand-ins (src/startup_stubs/profile_zone.h).
# One shared TracyClient.dll serves every instrumented DLL. Off (the default), nothing is fetched, defined or linked.
# On, Tracy (BSD-3-Clause, see docs/startup-runtime.md) is fetched at the pinned commit below, or taken from an existing
# checkout with -DFETCHCONTENT_SOURCE_DIR_TRACY=<path>. The client opens a local socket; see docs/startup-runtime.md.
option(X2W_TRACY "Instrument the startup stand-ins with Tracy zones and memory pools (fetches Tracy v0.15.0)" OFF)
if(X2W_TRACY)
    include(FetchContent)
    set(CMAKE_POLICY_DEFAULT_CMP0091 NEW)  # Tracy's 3.13 minimum would otherwise ignore MSVC_RUNTIME_LIBRARY
    set(TRACY_ENABLE ON)
    set(TRACY_STATIC OFF)
    set(TRACY_ON_DEMAND ON)
    set(TRACY_ONLY_LOCALHOST ON)
    set(TRACY_NO_BROADCAST ON)
    set(TRACY_NO_CRASH_HANDLER ON)
    # Symbol and kernel-tracing setup cost seconds per process in the D3D12 fixtures; sampling is ETW's job.
    set(TRACY_NO_CALLSTACK ON)
    set(TRACY_NO_SYSTEM_TRACING ON)
    # v0.15.0, pinned by commit so the tag cannot move.
    FetchContent_Declare(tracy GIT_REPOSITORY https://github.com/wolfpld/tracy.git
        GIT_TAG f2a4f2529e7e71844c9e434b877770a21ecf7587)
    FetchContent_MakeAvailable(tracy)
    set_target_properties(TracyClient PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
    foreach(target IN ITEMS d3d12_xs_shim startup_stub_xcrdapi xmem_shim)
        target_link_libraries(${target} PRIVATE Tracy::TracyClient)
        target_compile_definitions(${target} PRIVATE X2W_TRACY=1 X2W_TRACY_HEAP="${target} C++ heap")
        target_sources(${target} PRIVATE src/startup_stubs/tracy_new.cpp)
    endforeach()
endif()
add_executable(startup_null_views_check tests/startup_null_views_check.cpp)
target_compile_features(startup_null_views_check PRIVATE cxx_std_17)
target_link_libraries(startup_null_views_check PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS hardware warp)
    add_test(NAME startup_null_views_${adapter} COMMAND startup_null_views_check ${adapter})
endforeach()
set_tests_properties(startup_null_views_hardware PROPERTIES SKIP_RETURN_CODE 77)
# Device slot 15 (GetDescriptorHandleIncrementSize, #870) next to a desktop device on the same adapter.
add_executable(startup_descriptor_increment tests/startup_descriptor_increment.cpp)
target_compile_features(startup_descriptor_increment PRIVATE cxx_std_17)
target_link_libraries(startup_descriptor_increment PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS hardware warp)
    add_test(NAME startup_descriptor_increment_${adapter} COMMAND startup_descriptor_increment ${adapter})
endforeach()
set_tests_properties(startup_descriptor_increment_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(startup_descriptor_increment_hardware startup_descriptor_increment_warp PROPERTIES TIMEOUT 60
    ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=1")
# Which heap type values slot 15 forwards to desktop (src/startup_stubs/descriptor_heap_type.h), without a
# device. The mutated runs are the negative controls.
add_executable(startup_descriptor_heap_type_check tests/startup_descriptor_heap_type_check.cpp)
target_include_directories(startup_descriptor_heap_type_check PRIVATE src)
target_compile_features(startup_descriptor_heap_type_check PRIVATE cxx_std_17)
add_test(NAME startup_descriptor_heap_type COMMAND startup_descriptor_heap_type_check)
add_test(NAME startup_descriptor_heap_type_off_by_one_control COMMAND startup_descriptor_heap_type_check --mutate off-by-one)
add_test(NAME startup_descriptor_heap_type_signed_control COMMAND startup_descriptor_heap_type_check --mutate signed)
set_tests_properties(startup_descriptor_heap_type_off_by_one_control startup_descriptor_heap_type_signed_control PROPERTIES WILL_FAIL TRUE)
# The same header without a GPU (src/startup_stubs/null_texture_view.h): fake adapters that lack
# or have each use, R8G8B8A8 with one use, only B8G8R8A8, and failed queries. WARP has both uses, so
# only this check reaches the rewrite on CI. The mutated run is the negative control.
add_executable(startup_null_texture_view_check tests/startup_null_texture_view_check.cpp)
target_include_directories(startup_null_texture_view_check PRIVATE src)
target_compile_features(startup_null_texture_view_check PRIVATE cxx_std_17)
add_test(NAME startup_null_texture_view COMMAND startup_null_texture_view_check)
add_test(NAME startup_null_texture_view_unchecked_fallback_control COMMAND startup_null_texture_view_check --mutate unchecked-fallback)
set_tests_properties(startup_null_texture_view_unchecked_fallback_control PROPERTIES WILL_FAIL TRUE)
# Device views with ViewDimension 0 (UNKNOWN) or a dimension that does not fit the resource
# (src/startup_stubs/view_dimension.h). The control must FAIL.
add_executable(startup_view_dimension tests/startup_view_dimension_check.cpp)
target_include_directories(startup_view_dimension PRIVATE src)
target_compile_features(startup_view_dimension PRIVATE cxx_std_17)
add_test(NAME startup_view_dimension COMMAND startup_view_dimension)
add_test(NAME startup_view_dimension_control COMMAND startup_view_dimension --control)
set_tests_properties(startup_view_dimension_control PROPERTIES PASS_REGULAR_EXPRESSION "FAIL: ")
# The same through d3d12_xs.dll: an unknown-dimension SRV samples its texture's colour, an incompatible explicit SRV is
# refused without device removal, and a refused replacement leaves a null descriptor, not the slot's old view. The
# off control (X2W_D3D12_VIEW_DEFAULTS=off) must fail on the missing default view alone, with the device not removed.
add_executable(startup_view_dimension_device tests/startup_view_dimension_device.cpp)
target_compile_features(startup_view_dimension_device PRIVATE cxx_std_17)
target_link_libraries(startup_view_dimension_device PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_view_dimension_${backend} COMMAND startup_view_dimension_device ${backend})
    set_tests_properties(startup_view_dimension_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=0")
endforeach()
add_test(NAME startup_view_dimension_off_control_warp COMMAND startup_view_dimension_device warp off)
set_tests_properties(startup_view_dimension_off_control_warp PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
    ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=0;X2W_D3D12_VIEW_DEFAULTS=off"
    PASS_REGULAR_EXPRESSION "FAIL: \\(a\\) default view reads 0\\.000 0\\.000 0\\.000 0\\.000, expected 0\\.200 0\\.600 0\\.800 1\\.000; device not removed.*cases complete"
    FAIL_REGULAR_EXPRESSION "FAIL: setup|FAIL: \\(b\\)|FAIL: \\(c\\)|FAIL: \\(d\\)|DEVICE REMOVED|removed the device")
# The slot and label of the x2w-render totals line each null-binding cause is counted under
# (src/startup_stubs/null_binding_cause.h). The mutated run is the negative control.
add_executable(startup_null_cause_labels_check tests/startup_null_cause_labels_check.cpp)
target_include_directories(startup_null_cause_labels_check PRIVATE src)
target_compile_features(startup_null_cause_labels_check PRIVATE cxx_std_17)
add_test(NAME startup_null_cause_labels COMMAND startup_null_cause_labels_check)
add_test(NAME startup_null_cause_labels_buffer_token_control COMMAND startup_null_cause_labels_check --mutate buffer-token)
set_tests_properties(startup_null_cause_labels_buffer_token_control PROPERTIES WILL_FAIL TRUE)
# The opt-in API trace reads only declared outputs; this checks the decision about what it observed
# (argument index 0, two outputs, exact and short buffers, same value, partial comparison) and each
# declared contract. The mutated run is the negative control.
add_executable(api_trace_check tests/api_trace_check.cpp)
target_compile_features(api_trace_check PRIVATE cxx_std_17)
target_include_directories(api_trace_check PRIVATE src)
add_test(NAME api_trace COMMAND api_trace_check)
add_test(NAME api_trace_slot_only_control COMMAND api_trace_check --mutate slot-only)
set_tests_properties(api_trace_slot_only_control PROPERTIES WILL_FAIL TRUE)
# A view heap larger than the adapter accepts: the stand-in creates the desktop heap at the measured
# limit and keeps the title's full-size memory. Skips where the adapter accepts the full request.
add_executable(startup_view_heap_check tests/startup_view_heap_check.cpp)
target_compile_features(startup_view_heap_check PRIVATE cxx_std_17)
target_link_libraries(startup_view_heap_check PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS hardware warp)
    add_test(NAME startup_view_heap_${adapter} COMMAND startup_view_heap_check ${adapter} "${CMAKE_CURRENT_BINARY_DIR}/startup_view_heap_${adapter}.log")
    set_tests_properties(startup_view_heap_${adapter} PROPERTIES SKIP_RETURN_CODE 77)
endforeach()
add_executable(startup_stub_consumer tests/startup_stub_consumer.cpp)
add_executable(startup_gameinput_keys tests/startup_gameinput_keys.cpp)
target_compile_features(startup_gameinput_keys PRIVATE cxx_std_17)
add_test(NAME startup_gameinput_keys COMMAND startup_gameinput_keys "$<TARGET_FILE:startup_stub_gameinput>")
add_executable(startup_gameinput_history tests/startup_gameinput_history.cpp)
target_compile_features(startup_gameinput_history PRIVATE cxx_std_17)
add_test(NAME startup_gameinput_history COMMAND startup_gameinput_history "$<TARGET_FILE:startup_stub_gameinput>")
set_tests_properties(startup_gameinput_history PROPERTIES RUN_SERIAL TRUE)
add_executable(startup_gameinput_script tests/startup_gameinput_script.cpp)
target_compile_features(startup_gameinput_script PRIVATE cxx_std_17)
foreach(mode IN ITEMS long entries)
    add_test(NAME startup_gameinput_script_${mode} COMMAND startup_gameinput_script "$<TARGET_FILE:startup_stub_gameinput>" ${mode})
    set_tests_properties(startup_gameinput_script_${mode} PROPERTIES RUN_SERIAL TRUE)
endforeach()
add_executable(startup_gameinput_contracts_check tests/startup_gameinput_contracts_check.cpp)
target_compile_features(startup_gameinput_contracts_check PRIVATE cxx_std_17)
add_dependencies(startup_gameinput_contracts_check startup_stub_gameinput)
add_test(NAME startup_gameinput_contracts_check COMMAND startup_gameinput_contracts_check "$<TARGET_FILE:startup_stub_gameinput>")
set_tests_properties(startup_gameinput_contracts_check PROPERTIES TIMEOUT 60 RUN_SERIAL TRUE)
add_executable(startup_gameinput_script_syntax tests/startup_gameinput_script_syntax.cpp)
target_include_directories(startup_gameinput_script_syntax PRIVATE src)
target_compile_features(startup_gameinput_script_syntax PRIVATE cxx_std_17)
add_test(NAME startup_gameinput_script_syntax COMMAND startup_gameinput_script_syntax "$<TARGET_FILE:startup_stub_gameinput>")
set_tests_properties(startup_gameinput_script_syntax PROPERTIES RUN_SERIAL TRUE SKIP_RETURN_CODE 77)
add_executable(startup_present_signature tests/startup_present_signature.cpp)
target_include_directories(startup_present_signature PRIVATE src)
target_compile_features(startup_present_signature PRIVATE cxx_std_17)
target_link_libraries(startup_present_signature PRIVATE d3d12 dxgi)
add_test(NAME startup_present_signature_warp COMMAND startup_present_signature)
set_tests_properties(startup_present_signature_warp PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
# The sampler holds the presented surface until its copy has finished: a stalled queue, the caller's
# release after the present, then the signature, all under the debug layer. The control repeats the
# stall with a copy that does not hold its source and passes only if the debug layer reports it.
add_test(NAME startup_present_signature_held_source_warp COMMAND startup_present_signature held_source)
set_tests_properties(startup_present_signature_held_source_warp PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
add_test(NAME startup_present_signature_unheld_source_control_warp COMMAND startup_present_signature unheld_control)
set_tests_properties(startup_present_signature_unheld_source_control_warp PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)

if(EXISTS "${INTAKE_PYTHON}")
    add_executable(startup_present_producer tests/startup_present_producer.cpp)
    target_compile_features(startup_present_producer PRIVATE cxx_std_17)
    target_link_libraries(startup_present_producer PRIVATE d3d12_xs_shim d3d12 dxgi)
    foreach(backend IN ITEMS warp hardware)
        add_test(NAME startup_present_producer_${backend} COMMAND "${INTAKE_PYTHON}" -B
                 "${CMAKE_SOURCE_DIR}/tests/startup_present_producer_check.py" "${backend}" "$<TARGET_FILE:startup_present_producer>")
        set_tests_properties(startup_present_producer_${backend} PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 90)
        add_test(NAME startup_list_uav_barriers_${backend} COMMAND "${INTAKE_PYTHON}" -B
                 "${CMAKE_SOURCE_DIR}/tests/startup_present_producer_check.py" "${backend}" "$<TARGET_FILE:startup_present_producer>" barriers)
        set_tests_properties(startup_list_uav_barriers_${backend} PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
    endforeach()
endif()
add_executable(startup_placement_alloc tests/startup_placement_alloc.cpp)
target_compile_features(startup_placement_alloc PRIVATE cxx_std_17)
target_include_directories(startup_placement_alloc PRIVATE src)
add_test(NAME startup_placement_alloc COMMAND startup_placement_alloc)
# The same registration under the lock held exclusively, and max_width kept at the widest record
# (src/startup_stubs/placement_publish.h). The mutated run is the negative control.
add_executable(startup_placement_publish_check tests/startup_placement_publish_check.cpp)
target_compile_features(startup_placement_publish_check PRIVATE cxx_std_17)
target_include_directories(startup_placement_publish_check PRIVATE src)
add_test(NAME startup_placement_publish COMMAND startup_placement_publish_check)
add_test(NAME startup_placement_publish_shrink_control COMMAND startup_placement_publish_check --mutate shrink)
set_tests_properties(startup_placement_publish_shrink_control PROPERTIES WILL_FAIL TRUE)
# The memory SRV address lookups through src/startup_stubs/resource_address_index.h answer what a scan of
# every resource answers, across release, re-reference, address reuse and allocation failures at the index
# insert. The skip run (one insert dropped) and the unsync run (index insert first, kept when the record
# update fails) are the negative controls.
add_executable(startup_resource_address_index_check tests/startup_resource_address_index_check.cpp)
target_compile_features(startup_resource_address_index_check PRIVATE cxx_std_17)
target_include_directories(startup_resource_address_index_check PRIVATE src)
# The 180000 lookups walk std::multimap and std::map nodes; MSVC Debug iterator checks (level 2) made that take
# minutes. The test checks the lookup answers, not iterator validity, so this one target runs without them.
target_compile_definitions(startup_resource_address_index_check PRIVATE $<$<AND:$<CXX_COMPILER_ID:MSVC>,$<CONFIG:Debug>>:_ITERATOR_DEBUG_LEVEL=0>)
add_test(NAME startup_resource_address_index COMMAND startup_resource_address_index_check)
add_test(NAME startup_resource_address_index_skip_control COMMAND startup_resource_address_index_check --mutate skip)
add_test(NAME startup_resource_address_index_unsync_control COMMAND startup_resource_address_index_check --mutate unsync)
set_tests_properties(startup_resource_address_index_skip_control startup_resource_address_index_unsync_control PROPERTIES WILL_FAIL TRUE)
# Device slot 133 proves that the allocation is committed from its base to the end of the buffer with
# one region-information call when the whole private allocation is committed, else with a walk that
# stops at the end of the buffer; every alias or refusal must equal the full walk's on the same memory,
# including a decommitted page before the buffer and a block replaced at the same base, and a large
# touched block must need no VirtualQuery (src/startup_stubs/placed_buffer_range.h). The mutated runs
# are the negative controls; each passes only when it fails exactly for its stated reason.
add_executable(startup_placed_buffer_range_check tests/startup_placed_buffer_range_check.cpp)
target_compile_features(startup_placed_buffer_range_check PRIVATE cxx_std_17)
target_include_directories(startup_placed_buffer_range_check PRIVATE src)
add_test(NAME startup_placed_buffer_range COMMAND startup_placed_buffer_range_check)
add_test(NAME startup_placed_buffer_range_region_only_control COMMAND startup_placed_buffer_range_check --mutate region-only)
add_test(NAME startup_placed_buffer_range_walk_only_control COMMAND startup_placed_buffer_range_check --mutate walk-only)
set_tests_properties(startup_placed_buffer_range_region_only_control startup_placed_buffer_range_walk_only_control
    PROPERTIES SKIP_RETURN_CODE 77)
# CopyTextureRegion (list slot 16): the argument checks refuse what the desktop would reject
# (src/startup_stubs/list_copy_texture.h). The mutated run is the negative control.
add_executable(startup_list_copy_texture_check tests/startup_list_copy_texture_check.cpp)
target_compile_features(startup_list_copy_texture_check PRIVATE cxx_std_17)
target_include_directories(startup_list_copy_texture_check PRIVATE src)
add_test(NAME startup_list_copy_texture COMMAND startup_list_copy_texture_check)
add_test(NAME startup_list_copy_texture_overflow_control COMMAND startup_list_copy_texture_check --mutate overflow)
set_tests_properties(startup_list_copy_texture_overflow_control PROPERTIES WILL_FAIL TRUE)
add_test(NAME startup_list_copy_texture_slice_control COMMAND startup_list_copy_texture_check --mutate slice)
set_tests_properties(startup_list_copy_texture_slice_control PROPERTIES WILL_FAIL TRUE)

# The same call through the wrapped command list: two array slices round-trip, and an out-of-range subresource
# or a format mismatch is refused before any desktop copy.
add_executable(startup_list_copy_texture_warp tests/startup_list_copy_texture_warp.cpp)
target_compile_features(startup_list_copy_texture_warp PRIVATE cxx_std_17)
target_link_libraries(startup_list_copy_texture_warp PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_list_copy_texture_${backend} COMMAND startup_list_copy_texture_warp ${backend})
    set_tests_properties(startup_list_copy_texture_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
endforeach()
add_executable(startup_storage_file_range tests/startup_storage_file_range.cpp)
target_compile_features(startup_storage_file_range PRIVATE cxx_std_17)
target_include_directories(startup_storage_file_range PRIVATE src)
add_test(NAME startup_storage_file_range COMMAND startup_storage_file_range)
# The same read at offsets that need the high half of the OVERLAPPED position, in a sparse
# 4 GiB + 20 byte temporary file (src/startup_stubs/dstorage_file_read.h). 77 without sparse files.
add_executable(startup_dstorage_file_read_check tests/startup_dstorage_file_read_check.cpp)
target_compile_features(startup_dstorage_file_read_check PRIVATE cxx_std_17)
target_include_directories(startup_dstorage_file_read_check PRIVATE src)
add_test(NAME startup_dstorage_file_read COMMAND startup_dstorage_file_read_check)
add_test(NAME startup_dstorage_file_read_alias_control COMMAND startup_dstorage_file_read_check --mutate alias)
set_tests_properties(startup_dstorage_file_read startup_dstorage_file_read_alias_control PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(startup_dstorage_file_read_alias_control PROPERTIES WILL_FAIL TRUE)
add_executable(startup_inflate_status tests/startup_inflate_status.cpp)
target_compile_features(startup_inflate_status PRIVATE cxx_std_17)
target_include_directories(startup_inflate_status PRIVATE src)
add_test(NAME startup_inflate_status COMMAND startup_inflate_status)
# An allocation failure on the DirectStorage stand-in's worker fails that request, and the worker
# serves the next one (#1199). Skips (77) where the system does not enforce a job commit limit.
add_executable(startup_storage_alloc_failure tests/startup_storage_alloc_failure.cpp)
target_compile_features(startup_storage_alloc_failure PRIVATE cxx_std_17)
target_link_libraries(startup_storage_alloc_failure PRIVATE psapi)
add_dependencies(startup_storage_alloc_failure startup_stub_xcrdapi)
add_test(NAME startup_storage_alloc_failure COMMAND startup_storage_alloc_failure "$<TARGET_FILE:startup_stub_xcrdapi>")
set_tests_properties(startup_storage_alloc_failure PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
# A refused file request (offset at the end of the file, implausible size; raw and zlib) leaves its destination
# untouched, fails its status entry, and the requests around it in the same Submit complete in order (#1586).
add_executable(startup_storage_refusal_order tests/startup_storage_refusal_order.cpp)
target_compile_features(startup_storage_refusal_order PRIVATE cxx_std_17)
add_dependencies(startup_storage_refusal_order startup_stub_xcrdapi)
add_test(NAME startup_storage_refusal_order COMMAND startup_storage_refusal_order "$<TARGET_FILE:startup_stub_xcrdapi>")
set_tests_properties(startup_storage_refusal_order PROPERTIES TIMEOUT 60)
# Failed requests counted by cause for the heartbeat (#1198): at or past EOF, crossing EOF, other read
# failure, destination capacity, non-writable destination, zlib, BCPack, other. The test compiles the
# stand-in's source into itself to read the counters; the one-bucket expectations are the negative control.
add_executable(startup_storage_failure_counts tests/startup_storage_failure_counts.cpp)
target_compile_features(startup_storage_failure_counts PRIVATE cxx_std_17)
target_include_directories(startup_storage_failure_counts PRIVATE src)
target_link_libraries(startup_storage_failure_counts PRIVATE psapi)
add_test(NAME startup_storage_failure_counts COMMAND startup_storage_failure_counts)
add_test(NAME startup_storage_failure_counts_one_bucket_control COMMAND startup_storage_failure_counts --mutate one-bucket)
set_tests_properties(startup_storage_failure_counts startup_storage_failure_counts_one_bucket_control PROPERTIES TIMEOUT 60)
set_tests_properties(startup_storage_failure_counts_one_bucket_control PROPERTIES WILL_FAIL TRUE)
# Page-destination requests counted by where page_offset + destination_size ends against the first 64 KiB
# page (inside, at its end, past it), each as completed or failed, for the heartbeat (#1198). The test
# compiles the stand-in's source into itself and loads the xmem shim for page writes; the one-bucket
# expectations are the negative control.
add_executable(startup_storage_page_end_counts tests/startup_storage_page_end_counts.cpp)
target_compile_features(startup_storage_page_end_counts PRIVATE cxx_std_17)
target_include_directories(startup_storage_page_end_counts PRIVATE src)
target_link_libraries(startup_storage_page_end_counts PRIVATE psapi)
add_dependencies(startup_storage_page_end_counts xmem_shim)
add_test(NAME startup_storage_page_end_counts COMMAND startup_storage_page_end_counts "$<TARGET_FILE:xmem_shim>")
add_test(NAME startup_storage_page_end_counts_one_bucket_control
         COMMAND startup_storage_page_end_counts "$<TARGET_FILE:xmem_shim>" --mutate one-bucket)
set_tests_properties(startup_storage_page_end_counts startup_storage_page_end_counts_one_bucket_control PROPERTIES TIMEOUT 60)
set_tests_properties(startup_storage_page_end_counts_one_bucket_control PROPERTIES WILL_FAIL TRUE)
# A matched pair of page-destination zlib requests ending at the first page's end (#1198): one completes,
# one is refused for capacity. Read through XMemMapPhysicalPages views at each fence and after, the refused
# page keeps its sentinel; the pages are then unmapped and freed and a follow-up of the same shape completes.
# The accept-refused control takes the refused destination as data and must fail on that check.
add_executable(startup_storage_consumer_pair tests/startup_storage_consumer_pair.cpp)
target_compile_features(startup_storage_consumer_pair PRIVATE cxx_std_17)
add_dependencies(startup_storage_consumer_pair startup_stub_xcrdapi xmem_shim)
add_test(NAME startup_storage_consumer_pair
         COMMAND startup_storage_consumer_pair "$<TARGET_FILE:startup_stub_xcrdapi>" "$<TARGET_FILE:xmem_shim>")
add_test(NAME startup_storage_consumer_pair_accept_refused_control
         COMMAND startup_storage_consumer_pair "$<TARGET_FILE:startup_stub_xcrdapi>" "$<TARGET_FILE:xmem_shim>"
                 --mutate accept-refused)
set_tests_properties(startup_storage_consumer_pair startup_storage_consumer_pair_accept_refused_control PROPERTIES TIMEOUT 60)
set_tests_properties(startup_storage_consumer_pair_accept_refused_control PROPERTIES PASS_REGULAR_EXPRESSION
    "FAIL: after both fences: R destination taken as data differs from the stream prefix in 4096 byte\\(s\\), first at 0xf000")
# The same page followed through a refused request, a later valid write and a later refused write, without
# a release in between (#1198). Statuses stay per entry (R1 stays E_FAIL after V succeeds); the refused R2
# leaves V's bytes untouched. The accept-refused control takes R1's destination as data and must fail.
add_executable(startup_storage_refused_reuse tests/startup_storage_refused_reuse.cpp)
target_compile_features(startup_storage_refused_reuse PRIVATE cxx_std_17)
add_dependencies(startup_storage_refused_reuse startup_stub_xcrdapi xmem_shim)
add_test(NAME startup_storage_refused_reuse
         COMMAND startup_storage_refused_reuse "$<TARGET_FILE:startup_stub_xcrdapi>" "$<TARGET_FILE:xmem_shim>")
add_test(NAME startup_storage_refused_reuse_accept_refused_control
         COMMAND startup_storage_refused_reuse "$<TARGET_FILE:startup_stub_xcrdapi>" "$<TARGET_FILE:xmem_shim>"
                 --mutate accept-refused)
set_tests_properties(startup_storage_refused_reuse startup_storage_refused_reuse_accept_refused_control PROPERTIES TIMEOUT 60)
set_tests_properties(startup_storage_refused_reuse_accept_refused_control PROPERTIES PASS_REGULAR_EXPRESSION
    "FAIL: R1 destination taken as data matches the stream prefix in 0 of 4096 byte")

# #2788: the DirectStorage stand-in frees its COM objects at final Release, the queue's worker leaves
# before the queue is freed, and a pending entry keeps the status array and source file it uses alive
# after the guest releases them. The control deletes at zero without that accounting and must fail.
add_executable(startup_xcrdapi_lifetime tests/startup_xcrdapi_lifetime.cpp)
target_compile_features(startup_xcrdapi_lifetime PRIVATE cxx_std_17)
add_dependencies(startup_xcrdapi_lifetime startup_stub_xcrdapi)
add_test(NAME startup_xcrdapi_lifetime
         COMMAND startup_xcrdapi_lifetime "$<TARGET_FILE:startup_stub_xcrdapi>")
add_test(NAME startup_xcrdapi_lifetime_naive_control
         COMMAND startup_xcrdapi_lifetime "$<TARGET_FILE:startup_stub_xcrdapi>" control)
set_tests_properties(startup_xcrdapi_lifetime startup_xcrdapi_lifetime_naive_control PROPERTIES TIMEOUT 60)
set_tests_properties(startup_xcrdapi_lifetime_naive_control PROPERTIES WILL_FAIL TRUE)

# Test-only BCPack encoder (tests/bcpack_encoder.h): random synthetic streams must decode back to their
# symbols. Interleaving with a 7-byte cycle budget is the negative control.
add_executable(bcpack_encoder_check tests/bcpack_encoder_check.cpp)
target_compile_features(bcpack_encoder_check PRIVATE cxx_std_17)
target_include_directories(bcpack_encoder_check PRIVATE src)
add_test(NAME bcpack_encoder_roundtrip COMMAND bcpack_encoder_check)
add_test(NAME bcpack_encoder_window_control COMMAND bcpack_encoder_check --mutate window)
set_tests_properties(bcpack_encoder_roundtrip bcpack_encoder_window_control PROPERTIES TIMEOUT 120)
set_tests_properties(bcpack_encoder_window_control PROPERTIES WILL_FAIL TRUE)
# Each decode_lanes path against the original cycle loop on whole, truncated and bit-flipped streams
# (tests/bcpack_lanes_check.cpp), one test per path; 77 means this CPU lacks that path. The control
# build takes a wrong short DRAIN step at the home state and must fail on every path.
foreach(variant IN ITEMS check control)
    add_executable(bcpack_lanes_${variant} tests/bcpack_lanes_check.cpp)
    target_compile_features(bcpack_lanes_${variant} PRIVATE cxx_std_17)
    target_include_directories(bcpack_lanes_${variant} PRIVATE src)
    target_compile_definitions(bcpack_lanes_${variant} PRIVATE X2W_BCPACK_LANE_TESTS)
endforeach()
target_compile_definitions(bcpack_lanes_control PRIVATE X2W_BCPACK_LANES_CONTROL)
set(bcpack_lane_paths scalar avx2)
# Each path is also checked against outside anchors: the symbols stored in the repository vectors, the
# expected bytes in tests/bcpack_mode6_vector.py and tests/startup_stub_consumer.cpp, and the vendored
# Python decoder on a sample of streams (tests/bcpack_lanes_python_check.py).
foreach(path IN LISTS bcpack_lane_paths)
    add_test(NAME bcpack_lanes_${path} COMMAND bcpack_lanes_check "${CMAKE_SOURCE_DIR}/tools/_bcpack_rans/vectors"
             --path ${path} --consumer "${CMAKE_SOURCE_DIR}/tests/startup_stub_consumer.cpp")
    add_test(NAME bcpack_lanes_${path}_drain_control
             COMMAND bcpack_lanes_control "${CMAKE_SOURCE_DIR}/tools/_bcpack_rans/vectors" --path ${path})
    set(bcpack_lane_tests bcpack_lanes_${path} bcpack_lanes_${path}_drain_control)
    if(EXISTS "${INTAKE_PYTHON}")
        foreach(variant IN ITEMS check control)
            set(name bcpack_lanes_python_${path})
            if(variant STREQUAL control)
                set(name bcpack_lanes_python_${path}_drain_control)
            endif()
            add_test(NAME ${name} COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/bcpack_lanes_python_check.py"
                     "$<TARGET_FILE:bcpack_lanes_${variant}>" "${CMAKE_SOURCE_DIR}/tools/_bcpack_rans/vectors" --path ${path})
            list(APPEND bcpack_lane_tests ${name})
        endforeach()
        set_tests_properties(bcpack_lanes_python_${path}_drain_control PROPERTIES
            PASS_REGULAR_EXPRESSION "${path} path, [0-9]+ bytes, widths .*: Python accepts, C\\+\\+ rejects")
    endif()
    set_tests_properties(${bcpack_lane_tests} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    # Both the vector symbols and the reference sweep must catch the control build.
    set_tests_properties(bcpack_lanes_${path}_drain_control PROPERTIES PASS_REGULAR_EXPRESSION
        "${path} path: synthetic_11 lane [0-9]+ differs from the vector's symbols.*result: anchors failed, [1-9][0-9]* mismatches")
endforeach()
# A queue whose worker cannot start (both CreateThread attempts fail, or the construction of its work
# throws std::bad_alloc) completes status entries and fences at Submit, never inside Enqueue (#1199).
# The test compiles the stand-in's source into itself so it can redirect CreateThread and operator new.
add_executable(startup_dstorage_destination_check tests/startup_dstorage_destination_check.cpp)
target_compile_features(startup_dstorage_destination_check PRIVATE cxx_std_17)
add_dependencies(startup_dstorage_destination_check startup_stub_xcrdapi)
add_test(NAME startup_dstorage_destination COMMAND startup_dstorage_destination_check "$<TARGET_FILE:startup_stub_xcrdapi>")
set_tests_properties(startup_dstorage_destination PROPERTIES TIMEOUT 60)
add_executable(startup_storage_worker_start tests/startup_storage_worker_start.cpp)
target_compile_features(startup_storage_worker_start PRIVATE cxx_std_17)
target_include_directories(startup_storage_worker_start PRIVATE src)
target_link_libraries(startup_storage_worker_start PRIVATE psapi)
add_test(NAME startup_storage_worker_start COMMAND startup_storage_worker_start)
set_tests_properties(startup_storage_worker_start PROPERTIES TIMEOUT 60)
target_compile_features(startup_stub_consumer PRIVATE cxx_std_17)
target_include_directories(startup_stub_consumer PRIVATE src)
target_sources(startup_stub_consumer PRIVATE src/startup_stubs/runtime_proxy.cpp)
target_link_libraries(startup_stub_consumer PRIVATE startup_stub_chad startup_stub_xg_xs xmem_shim d3d12_xs_shim psapi)
# APU heap stand-in: ApuFree reuse, coalescing, refused requests and concurrent callers (docs/startup-runtime.md).
add_executable(startup_acphal_apu_free tests/startup_acphal_apu_free.cpp)
target_compile_features(startup_acphal_apu_free PRIVATE cxx_std_17)
add_dependencies(startup_acphal_apu_free startup_stub_acphal)
add_test(NAME startup_acphal_apu_free COMMAND startup_acphal_apu_free "$<TARGET_FILE:startup_stub_acphal>")
set_tests_properties(startup_acphal_apu_free PROPERTIES TIMEOUT 60)

add_executable(startup_xapu_queue_check tests/startup_xapu_queue_check.cpp)
target_compile_features(startup_xapu_queue_check PRIVATE cxx_std_17)
add_dependencies(startup_xapu_queue_check startup_stub_xapu)
add_test(NAME startup_xapu_queue COMMAND startup_xapu_queue_check "$<TARGET_FILE:startup_stub_xapu>")
set_tests_properties(startup_xapu_queue PROPERTIES TIMEOUT 60)
if(X2W_WITH_OPUS)
    # Encodes generated tones with the same libopus at test time; no binary fixtures.
    add_executable(startup_xapu_opus_check tests/startup_xapu_opus_check.cpp)
    target_compile_features(startup_xapu_opus_check PRIVATE cxx_std_17)
    target_link_libraries(startup_xapu_opus_check PRIVATE Opus::opus)
    set_target_properties(startup_xapu_opus_check PROPERTIES MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    add_dependencies(startup_xapu_opus_check startup_stub_xapu)
    add_test(NAME startup_xapu_opus COMMAND startup_xapu_opus_check "$<TARGET_FILE:startup_stub_xapu>")
    set_tests_properties(startup_xapu_opus PROPERTIES TIMEOUT 60)
endif()

add_executable(startup_chad_check tests/startup_chad_check.cpp)
target_compile_features(startup_chad_check PRIVATE cxx_std_17)
add_dependencies(startup_chad_check startup_stub_chad)
add_test(NAME startup_chad_check COMMAND startup_chad_check "$<TARGET_FILE:startup_stub_chad>")
set_tests_properties(startup_chad_check PROPERTIES TIMEOUT 60)

# BMP writer of the draw dumps (src/startup_stubs/draw_bmp.h); the mutated runs are negative controls.
add_executable(startup_draw_bmp_check tests/startup_draw_bmp.cpp)
add_test(NAME startup_draw_bmp COMMAND startup_draw_bmp_check)
foreach(mutation IN ITEMS tight wrap size-image)
    add_test(NAME startup_draw_bmp_${mutation}_control COMMAND startup_draw_bmp_check --mutate ${mutation})
    set_tests_properties(startup_draw_bmp_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# Names the x2w-noop log gives to command list slots (src/startup_stubs/command_list_slot_names.h, #870).
add_executable(startup_command_list_slot_names tests/startup_command_list_slot_names.cpp)
target_compile_features(startup_command_list_slot_names PRIVATE cxx_std_17)
add_test(NAME startup_command_list_slot_names COMMAND startup_command_list_slot_names)
# Root constants kept per recorded list (src/startup_stubs/root_constant_store.h, compute list slots 37 and 39, #870; slot 40 keeps its own graphics words).
add_executable(startup_root_constant_store tests/startup_root_constant_store.cpp)
target_compile_features(startup_root_constant_store PRIVATE cxx_std_17)
add_test(NAME startup_root_constant_store COMMAND startup_root_constant_store)
# Game-save stand-in storage (src/startup_stubs/save_store.h): a blob written by one process is read by a second.
add_executable(startup_gamesave_persist tests/startup_gamesave_persist.cpp)
target_compile_features(startup_gamesave_persist PRIVATE cxx_std_17)
add_test(NAME startup_gamesave_persist COMMAND startup_gamesave_persist)
# Enumeration of the same store (Store::list_containers, Store::list_blobs): exact names, sizes and
# order, what is not listed, the busy and untouched-output rules, and a second process that
# publishes two-blob updates while this one lists.
add_executable(startup_gamesave_enumerate tests/startup_gamesave_enumerate.cpp)
target_compile_features(startup_gamesave_enumerate PRIVATE cxx_std_17)
add_test(NAME startup_gamesave_enumerate COMMAND startup_gamesave_enumerate)
set_tests_properties(startup_gamesave_enumerate PROPERTIES TIMEOUT 120)
# Publication of a multi-blob update: a second process sees the whole old generation or the whole
# new one. The test is built from two generated copies of the store headers, each with a pause
# point at every step of the publication (the `x2w-seam` comments). In the second copy the file lock
# is also turned into a no-op: that build must be caught by the same test, which proves the check
# can fail. Nothing of this reaches the production headers.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/startup_stubs/save_store.h" gamesave_store_text)
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/startup_stubs/file_lock.h" gamesave_lock_text)
foreach(anchor "#pragma once" "// x2w-seam: moved-aside" "// x2w-seam: published" "// x2w-seam: store-read" "// x2w-seam: blob-read")
    string(FIND "${gamesave_store_text}" "${anchor}" gamesave_anchor)
    if(gamesave_anchor LESS 0)
        message(FATAL_ERROR "save_store.h lost the anchor '${anchor}' used by startup_gamesave_publish")
    endif()
endforeach()
string(FIND "${gamesave_lock_text}" "// x2w-seam: lock-attempt" gamesave_anchor)
if(gamesave_anchor LESS 0)
    message(FATAL_ERROR "file_lock.h lost the anchor used by startup_gamesave_publish")
endif()
string(REPLACE "#pragma once" "#pragma once\nvoid x2w_save_test_point(unsigned point);" gamesave_store_text "${gamesave_store_text}")
string(REPLACE "// x2w-seam: moved-aside" "x2w_save_test_point(2u * static_cast<unsigned>(&step - steps.data()));" gamesave_store_text "${gamesave_store_text}")
string(REPLACE "// x2w-seam: published" "x2w_save_test_point(2u * static_cast<unsigned>(&step - steps.data()) + 1u);" gamesave_store_text "${gamesave_store_text}")
# Reader seams for startup_gamesave_read_publish: a hook that is null unless that test sets it.
string(REPLACE "void x2w_save_test_point(unsigned point);" "void x2w_save_test_point(unsigned point);\ninline void (*x2w_save_read_hook)(int point, unsigned long long index) = nullptr;" gamesave_store_text "${gamesave_store_text}")
string(REPLACE "// x2w-seam: store-read" "if (x2w_save_read_hook) x2w_save_read_hook(2, 0);" gamesave_store_text "${gamesave_store_text}")
string(REPLACE "// x2w-seam: blob-read" "if (x2w_save_read_hook) x2w_save_read_hook(0, i);" gamesave_store_text "${gamesave_store_text}")
string(REPLACE "// x2w-seam: lock-attempt" "static volatile bool x2w_no_lock = true;\n        if (x2w_no_lock) return Attempt::locked;" gamesave_nolock_text "${gamesave_lock_text}")
foreach(variant locked unlocked)
    set(gamesave_dir "${CMAKE_CURRENT_BINARY_DIR}/gamesave_publish_${variant}")
    file(WRITE "${gamesave_dir}/startup_stubs/save_store.h" "${gamesave_store_text}")
    if(variant STREQUAL "locked")
        file(WRITE "${gamesave_dir}/startup_stubs/file_lock.h" "${gamesave_lock_text}")
    else()
        file(WRITE "${gamesave_dir}/startup_stubs/file_lock.h" "${gamesave_nolock_text}")
    endif()
    add_executable(startup_gamesave_publish_${variant} tests/startup_gamesave_publish.cpp)
    target_include_directories(startup_gamesave_publish_${variant} PRIVATE "${gamesave_dir}")
    target_compile_features(startup_gamesave_publish_${variant} PRIVATE cxx_std_17)
    add_test(NAME startup_gamesave_publish_${variant} COMMAND startup_gamesave_publish_${variant})
    set_tests_properties(startup_gamesave_publish_${variant} PROPERTIES TIMEOUT 120)
    # The synchronous read (slot 20) against the same paused writer in a second process.
    add_executable(startup_gamesave_read_publish_${variant} tests/startup_gamesave_read_publish.cpp)
    target_include_directories(startup_gamesave_read_publish_${variant} PRIVATE "${gamesave_dir}" src)
    target_compile_features(startup_gamesave_read_publish_${variant} PRIVATE cxx_std_17)
    add_test(NAME startup_gamesave_read_publish_${variant} COMMAND startup_gamesave_read_publish_${variant})
    set_tests_properties(startup_gamesave_read_publish_${variant} PROPERTIES TIMEOUT 300)
endforeach()
# The copy without the lock must be caught by the reader that sees a mixed or incomplete generation.
set_tests_properties(startup_gamesave_publish_unlocked PROPERTIES PASS_REGULAR_EXPRESSION "reader saw a mixed generation")
set_tests_properties(startup_gamesave_read_publish_unlocked PROPERTIES PASS_REGULAR_EXPRESSION "reader saw a mixed generation")
add_executable(startup_gamesave_lock_errors tests/startup_gamesave_lock_errors.cpp)
target_include_directories(startup_gamesave_lock_errors PRIVATE src)
target_compile_features(startup_gamesave_lock_errors PRIVATE cxx_std_17)
add_test(NAME startup_gamesave_lock_errors COMMAND startup_gamesave_lock_errors)
# Negative control: the same check built against a generated copy of file_lock.h whose acquire no
# longer drops the lock the object already holds. The check must report that leaked lock. The copy
# exists only in the test build.
string(REGEX REPLACE "release\\(\\);([\r\n]+ +last_error_ = 0;)" "\\1" gamesave_lock_keep_text "${gamesave_lock_text}")
if(gamesave_lock_keep_text STREQUAL gamesave_lock_text)
    message(FATAL_ERROR "file_lock.h lost the release at the start of acquire used by startup_gamesave_lock_errors_reacquire_control")
endif()
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/gamesave_lock_keep/startup_stubs/file_lock.h" "${gamesave_lock_keep_text}")
add_executable(startup_gamesave_lock_errors_keep tests/startup_gamesave_lock_errors.cpp)
target_include_directories(startup_gamesave_lock_errors_keep PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/gamesave_lock_keep")
target_compile_features(startup_gamesave_lock_errors_keep PRIVATE cxx_std_17)
add_test(NAME startup_gamesave_lock_errors_reacquire_control COMMAND startup_gamesave_lock_errors_keep)
set_tests_properties(startup_gamesave_lock_errors_reacquire_control PROPERTIES PASS_REGULAR_EXPRESSION "FAIL: re-acquire")
add_executable(startup_gamesave_read tests/startup_gamesave_read.cpp)
target_include_directories(startup_gamesave_read PRIVATE src)
target_compile_features(startup_gamesave_read PRIVATE cxx_std_17)
add_executable(startup_gamesave_submit tests/startup_gamesave_submit.cpp)
target_include_directories(startup_gamesave_submit PRIVATE src)
target_compile_features(startup_gamesave_submit PRIVATE cxx_std_17)
add_executable(startup_gamesave_read_async tests/startup_gamesave_read_async.cpp)
target_include_directories(startup_gamesave_read_async PRIVATE src)
target_compile_features(startup_gamesave_read_async PRIVATE cxx_std_17)
add_executable(startup_async_manual_completion tests/startup_async_manual_completion.cpp)
target_compile_features(startup_async_manual_completion PRIVATE cxx_std_17)
foreach(scheduler IN ITEMS controlled system)
    add_test(NAME startup_async_manual_completion_${scheduler} COMMAND startup_async_manual_completion ${scheduler})
    set_tests_properties(startup_async_manual_completion_${scheduler} PROPERTIES TIMEOUT 30)
endforeach()
set_tests_properties(startup_async_manual_completion_system PROPERTIES SKIP_RETURN_CODE 77)
# Control: a stand-in that runs the callback inside Complete must fail the unpumped check.
add_test(NAME startup_async_manual_completion_inline_control COMMAND startup_async_manual_completion inline-control)
set_tests_properties(startup_async_manual_completion_inline_control PROPERTIES TIMEOUT 30
    PASS_REGULAR_EXPRESSION "FAIL: callback ran before the completion port was dispatched")
add_executable(startup_runtime_local tests/startup_runtime_local.cpp)
target_include_directories(startup_runtime_local PRIVATE src)
target_compile_features(startup_runtime_local PRIVATE cxx_std_17)
if (WIN32)
    target_link_libraries(startup_runtime_local PRIVATE psapi)
endif()
add_test(NAME startup_runtime_local COMMAND startup_runtime_local)
# Control: with the local runtime switch left off, the local answers must be missing.
add_test(NAME startup_runtime_local_control COMMAND startup_runtime_local --control)
set_tests_properties(startup_runtime_local_control PROPERTIES PASS_REGULAR_EXPRESSION "FAIL: ")
# Which PE imports the runtime proxy rewrites (GetProcAddress any module; QueryApiImpl only from
# xgameruntime.dll). Pure walk of a synthetic PE32+ image; the name-only mutate must FAIL.
add_executable(startup_runtime_gpa_patch tests/startup_runtime_gpa_patch_check.cpp)
target_include_directories(startup_runtime_gpa_patch PRIVATE src)
target_compile_features(startup_runtime_gpa_patch PRIVATE cxx_std_17)
add_test(NAME startup_runtime_gpa_patch COMMAND startup_runtime_gpa_patch)
add_test(NAME startup_runtime_gpa_patch_name_only_control COMMAND startup_runtime_gpa_patch --mutate name-only)
set_tests_properties(startup_runtime_gpa_patch_name_only_control PROPERTIES PASS_REGULAR_EXPRESSION "FAIL: ")
# X2W_DEVICE_TYPE: the OEM ConsoleMode registry read, answered or passed on, against fake registry
# functions. A source-built decoy DLL exports the same registry names and must stay unhooked. The
# control leaves the switch unset for the answered cases; the provider control matches registry
# imports by name alone. Both must FAIL.
add_library(startup_console_mode_decoy SHARED
    tests/startup_console_mode_decoy.cpp
    tests/startup_console_mode_decoy.def)
target_compile_features(startup_console_mode_decoy PRIVATE cxx_std_17)
add_executable(startup_console_mode tests/startup_console_mode_check.cpp)
target_include_directories(startup_console_mode PRIVATE src)
target_compile_features(startup_console_mode PRIVATE cxx_std_17)
add_dependencies(startup_console_mode startup_console_mode_decoy)
add_test(NAME startup_console_mode COMMAND startup_console_mode --decoy "$<TARGET_FILE:startup_console_mode_decoy>")
add_test(NAME startup_console_mode_control
         COMMAND startup_console_mode --control --decoy "$<TARGET_FILE:startup_console_mode_decoy>")
add_test(NAME startup_console_mode_provider_control
         COMMAND startup_console_mode --control provider --decoy "$<TARGET_FILE:startup_console_mode_decoy>")
set_tests_properties(startup_console_mode_control startup_console_mode_provider_control PROPERTIES PASS_REGULAR_EXPRESSION "FAIL: ")
# EXE + late-loaded package helper through the real Windows loader: proxied xgameruntime QueryApiImpl,
# unrelated same-named export stays original. Notification only enqueues; rewrite runs after link.
if (WIN32)
    set(X2W_PROXY_SCOPE_DIR "${CMAKE_CURRENT_BINARY_DIR}/startup_runtime_proxy_scope")
    add_library(startup_runtime_proxy_carrier SHARED
        tests/startup_runtime_proxy_scope/carrier.cpp
        src/startup_stubs/runtime_proxy.cpp)
    target_include_directories(startup_runtime_proxy_carrier PRIVATE src)
    target_compile_features(startup_runtime_proxy_carrier PRIVATE cxx_std_17)
    target_link_libraries(startup_runtime_proxy_carrier PRIVATE psapi)
    add_library(startup_runtime_proxy_helper SHARED
        tests/startup_runtime_proxy_scope/helper.cpp
        tests/startup_runtime_proxy_scope/helper.def)
    target_compile_features(startup_runtime_proxy_helper PRIVATE cxx_std_17)
    add_library(startup_runtime_proxy_xgr SHARED
        tests/startup_runtime_proxy_scope/xgameruntime.cpp
        tests/startup_runtime_proxy_scope/xgameruntime.def)
    target_compile_features(startup_runtime_proxy_xgr PRIVATE cxx_std_17)
    set_target_properties(startup_runtime_proxy_xgr PROPERTIES OUTPUT_NAME xgameruntime)
    add_library(startup_runtime_proxy_decoy SHARED
        tests/startup_runtime_proxy_scope/decoy.cpp
        tests/startup_runtime_proxy_scope/decoy.def)
    target_compile_features(startup_runtime_proxy_decoy PRIVATE cxx_std_17)
    add_executable(startup_runtime_proxy_scope tests/startup_runtime_proxy_scope/host.cpp)
    target_compile_features(startup_runtime_proxy_scope PRIVATE cxx_std_17)
    foreach(tgt IN ITEMS startup_runtime_proxy_carrier startup_runtime_proxy_helper startup_runtime_proxy_xgr
                         startup_runtime_proxy_decoy startup_runtime_proxy_scope)
        set_target_properties(${tgt} PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY "${X2W_PROXY_SCOPE_DIR}"
            LIBRARY_OUTPUT_DIRECTORY "${X2W_PROXY_SCOPE_DIR}"
            ARCHIVE_OUTPUT_DIRECTORY "${X2W_PROXY_SCOPE_DIR}")
    endforeach()
    add_dependencies(startup_runtime_proxy_scope startup_runtime_proxy_carrier startup_runtime_proxy_helper
                     startup_runtime_proxy_xgr startup_runtime_proxy_decoy)
    add_test(NAME startup_runtime_proxy_scope COMMAND "$<TARGET_FILE:startup_runtime_proxy_scope>")
    set_tests_properties(startup_runtime_proxy_scope PROPERTIES TIMEOUT 60 RUN_SERIAL TRUE)
endif()

# Input for the launcher containment check (docs/startup-runtime.md): writes known bytes to both
# streams and the trap log, reports a known exit code, or holds memory, spawns a child or stays
# alive so the launch tool's job limits have to stop it.
# Input for tests/startup_host_cpu_debug_check.py.
add_executable(startup_host_cpu_probe tests/startup_host_cpu_probe.cpp)
target_compile_features(startup_host_cpu_probe PRIVATE cxx_std_17)
# Placed buffers at the boundary between two views of physical pages (src/xmem_mapped_pages.cpp).
add_executable(xmem_page_runs_device_check tests/xmem_page_runs_device_check.cpp)
target_compile_features(xmem_page_runs_device_check PRIVATE cxx_std_17)
target_link_libraries(xmem_page_runs_device_check PRIVATE xmem_shim d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME xmem_page_runs_device_${adapter} COMMAND xmem_page_runs_device_check ${adapter})
    set_tests_properties(xmem_page_runs_device_${adapter} PROPERTIES TIMEOUT 120)
endforeach()
set_tests_properties(xmem_page_runs_device_hardware PROPERTIES SKIP_RETURN_CODE 77)
add_executable(startup_launch_probe tests/startup_launch_probe.cpp)
target_compile_features(startup_launch_probe PRIVATE cxx_std_17)
# Input for the startup debugger's diagnostics check (tests/startup_debug_check.py).
add_executable(startup_debug_probe tests/startup_debug_probe.cpp)
target_compile_features(startup_debug_probe PRIVATE cxx_std_17)
# The DLL the probe calls for the debugger's call-hook case (--trace-calls).
add_library(startup_debug_calls SHARED tests/startup_debug_calls.cpp)
add_dependencies(startup_debug_probe startup_debug_calls)
# Input for tests/startup_inflate_check.py: the DirectStorage stand-in's zlib decoder on one stream.
add_executable(startup_inflate_probe tests/startup_inflate_probe.cpp)
target_compile_features(startup_inflate_probe PRIVATE cxx_std_17)
target_include_directories(startup_inflate_probe PRIVATE src)
# The same probe decoding one bit at a time (the reference), and with one wrong table entry (the control);
# only the startup_inflate test uses them.
if(EXISTS "${INTAKE_PYTHON}")
    add_executable(startup_inflate_probe_bitwise tests/startup_inflate_probe.cpp)
    target_compile_features(startup_inflate_probe_bitwise PRIVATE cxx_std_17)
    target_include_directories(startup_inflate_probe_bitwise PRIVATE src)
    target_compile_definitions(startup_inflate_probe_bitwise PRIVATE X2W_INFLATE_FAST_BITS=0)
    add_executable(startup_inflate_probe_faulty tests/startup_inflate_probe.cpp)
    target_compile_features(startup_inflate_probe_faulty PRIVATE cxx_std_17)
    target_include_directories(startup_inflate_probe_faulty PRIVATE src)
    target_compile_definitions(startup_inflate_probe_faulty PRIVATE X2W_INFLATE_FAULTY_TABLE)
    # Controls for the fast loop: entered one output byte short of the longest match, entered with 7
    # input bytes left, and without its distance check.
    foreach(control IN ITEMS margin input_margin distance)
        add_executable(startup_inflate_probe_faulty_${control} tests/startup_inflate_probe.cpp)
        target_compile_features(startup_inflate_probe_faulty_${control} PRIVATE cxx_std_17)
        target_include_directories(startup_inflate_probe_faulty_${control} PRIVATE src)
        string(TOUPPER "${control}" control_macro)
        target_compile_definitions(startup_inflate_probe_faulty_${control} PRIVATE X2W_INFLATE_FAULTY_${control_macro})
    endforeach()
endif()

add_executable(startup_dump_fence_check tests/startup_dump_fence.cpp tests/desktop_gpu.cpp)
add_executable(startup_overlay_window tests/startup_overlay_window.cpp)
target_compile_features(startup_overlay_window PRIVATE cxx_std_17)
target_include_directories(startup_overlay_window PRIVATE src)
target_link_libraries(startup_overlay_window PRIVATE user32)
add_test(NAME startup_overlay_window COMMAND startup_overlay_window)
# WASAPI render sink (Refs #1145); exit 77 when the machine has no usable render endpoint. The sink is
# compiled once for this check and the pacing control below.
add_library(startup_audio_sink_obj OBJECT src/startup_stubs/audio_sink.cpp)
target_compile_features(startup_audio_sink_obj PRIVATE cxx_std_17)
target_include_directories(startup_audio_sink_obj PRIVATE src)
add_executable(startup_audio_output tests/startup_audio_output.cpp $<TARGET_OBJECTS:startup_audio_sink_obj>)
target_compile_features(startup_audio_output PRIVATE cxx_std_17)
target_include_directories(startup_audio_output PRIVATE src)
target_link_libraries(startup_audio_output PRIVATE ole32)
add_test(NAME startup_audio_output COMMAND startup_audio_output)
set_tests_properties(startup_audio_output PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
# Playback-timing control: the same sink and endpoint as startup_audio_output, fed steady and bursty,
# recording first submission, frame counts, clock, drained interval and recovery for comparison.
add_executable(startup_audio_pacing tests/startup_audio_pacing.cpp $<TARGET_OBJECTS:startup_audio_sink_obj>)
target_compile_features(startup_audio_pacing PRIVATE cxx_std_17)
target_include_directories(startup_audio_pacing PRIVATE src)
target_link_libraries(startup_audio_pacing PRIVATE ole32)
add_test(NAME startup_audio_pacing COMMAND startup_audio_pacing)
set_tests_properties(startup_audio_pacing PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 90)
# Voice-lifecycle control: one client, two explicit providers (a diagnostic recorder and the system
# XAudio2 called directly), verifying the diagnostic window observes the same lifecycle before any
# timing number from it is used.
add_executable(startup_audio_provider tests/startup_audio_provider.cpp)
target_compile_features(startup_audio_provider PRIVATE cxx_std_17)
target_include_directories(startup_audio_provider PRIVATE src)
target_link_libraries(startup_audio_provider PRIVATE ole32 xaudio2)
add_test(NAME startup_audio_provider COMMAND startup_audio_provider)
set_tests_properties(startup_audio_provider PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 120)
if(EXISTS "${INTAKE_PYTHON}")
    # Audio/input alignment control: generated packet statistics through tools/startup_audio_timeline.py.
    # It needs no audio device, no GPU and no game files.
    add_test(NAME startup_audio_timeline COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_audio_timeline_check.py")
    set_tests_properties(startup_audio_timeline PROPERTIES TIMEOUT 60)
    add_test(NAME startup_audio_timeline_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_audio_timeline_cli_check.py")
endif()
target_compile_features(startup_dump_fence_check PRIVATE cxx_std_17)
target_include_directories(startup_dump_fence_check PRIVATE src)
target_link_libraries(startup_dump_fence_check PRIVATE d3d12 dxgi)
add_test(NAME startup_dump_fence_warp COMMAND startup_dump_fence_check)
set_tests_properties(startup_dump_fence_warp PROPERTIES ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=warp" TIMEOUT 45)
# The control expects a capture whose fence reports device removal to be published, and must fail.
add_test(NAME startup_dump_fence_removed_control_warp COMMAND startup_dump_fence_check --mutate removed)
set_tests_properties(startup_dump_fence_removed_control_warp PROPERTIES ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=warp" TIMEOUT 45
    WILL_FAIL TRUE)

# Per-draw texel history: three source-built draws where only the second covers the watched texel,
# then a control without that draw. The report must name draw 2 and leave the texel black in the control.
add_executable(startup_pixel_history tests/startup_pixel_history.cpp tests/desktop_gpu.cpp)
target_compile_features(startup_pixel_history PRIVATE cxx_std_17)
target_include_directories(startup_pixel_history PRIVATE src)
target_link_libraries(startup_pixel_history PRIVATE d3d12 dxgi d3dcompiler)
add_test(NAME startup_pixel_history_warp COMMAND startup_pixel_history)
set_tests_properties(startup_pixel_history_warp PROPERTIES TIMEOUT 60)
add_test(NAME startup_pixel_history_hardware COMMAND startup_pixel_history hardware)
set_tests_properties(startup_pixel_history_hardware PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)

add_executable(startup_typed_buffer_view tests/startup_typed_buffer_view.cpp)
target_compile_features(startup_typed_buffer_view PRIVATE cxx_std_17)
add_test(NAME startup_typed_buffer_view COMMAND startup_typed_buffer_view)

# tests/startup_stream_setup.cpp is compiled once for the consumer and the depth check.
add_library(startup_stream_setup_obj OBJECT tests/startup_stream_setup.cpp)
target_compile_features(startup_stream_setup_obj PRIVATE cxx_std_17)
add_executable(startup_stream_consumer tests/startup_stream_consumer.cpp $<TARGET_OBJECTS:startup_stream_setup_obj> tests/startup_stream_draw.cpp
    tests/startup_address_srv.cpp tests/startup_root_cbv.cpp tests/startup_root_heap.cpp)
target_compile_features(startup_stream_consumer PRIVATE cxx_std_17)
target_link_libraries(startup_stream_consumer PRIVATE d3d12_xs_shim startup_stub_xg_xs d3d12 dxgi d3dcompiler)
target_sources(startup_stream_consumer PRIVATE tests/startup_frame_copy.cpp)
target_sources(startup_stream_consumer PRIVATE tests/startup_root_reset.cpp)
target_sources(startup_stream_consumer PRIVATE tests/startup_memory_srv_diag.cpp)
target_sources(startup_stream_consumer PRIVATE tests/startup_pixel_uav.cpp)
target_sources(startup_stream_consumer PRIVATE tests/startup_slot67_indirect.cpp tests/desktop_gpu.cpp)

add_executable(startup_stream_depth tests/startup_stream_depth.cpp $<TARGET_OBJECTS:startup_stream_setup_obj>)
target_compile_features(startup_stream_depth PRIVATE cxx_std_17)
target_link_libraries(startup_stream_depth PRIVATE d3d12_xs_shim d3d12 dxgi)
# X2W_DEPTH_STATE draw fixture (#1999, item A): slot 57 pipelines with depth-stencil register words.
add_executable(startup_slot57_depth tests/startup_slot57_depth.cpp $<TARGET_OBJECTS:startup_stream_setup_obj>)
target_compile_features(startup_slot57_depth PRIVATE cxx_std_17)
target_link_libraries(startup_slot57_depth PRIVATE d3d12_xs_shim d3d12 dxgi)
# Depth target binding for translated draws (list slot 50, #1999 item D): depth values and debug-layer
# messages after the fence, and an unresolved depth handle.
add_executable(startup_draw_depth_target tests/startup_draw_depth_target.cpp $<TARGET_OBJECTS:startup_stream_setup_obj>)
target_compile_features(startup_draw_depth_target PRIVATE cxx_std_17)
target_link_libraries(startup_draw_depth_target PRIVATE d3d12_xs_shim d3d12 dxgi)

add_executable(startup_stream_rasterizer tests/startup_stream_rasterizer.cpp $<TARGET_OBJECTS:startup_stream_setup_obj>)
target_compile_features(startup_stream_rasterizer PRIVATE cxx_std_17)
target_link_libraries(startup_stream_rasterizer PRIVATE d3d12_xs_shim d3d12 dxgi)

# Console queue Wait (slot 17) waits on the GPU instead of signalling the fence.
add_executable(startup_queue_wait tests/startup_queue_wait.cpp)
target_compile_features(startup_queue_wait PRIVATE cxx_std_17)
target_link_libraries(startup_queue_wait PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_queue_wait_${backend} COMMAND startup_queue_wait ${backend})
    set_tests_properties(startup_queue_wait_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=1")
endforeach()

# Console COPY queue page mappings through the installed XMem provider.
add_executable(startup_queue_page_batch tests/startup_queue_page_batch.cpp)
target_compile_features(startup_queue_page_batch PRIVATE cxx_std_17)
target_include_directories(startup_queue_page_batch PRIVATE src)
target_link_libraries(startup_queue_page_batch PRIVATE d3d12_xs_shim dxgi OneCore)
add_dependencies(startup_queue_page_batch xmem_shim)
add_test(NAME startup_queue_page_batch_warp COMMAND startup_queue_page_batch "$<TARGET_FILE:xmem_shim>")
add_test(NAME startup_queue_page_batch_runs_warp COMMAND startup_queue_page_batch "$<TARGET_FILE:xmem_shim>" runs)
set_tests_properties(startup_queue_page_batch_warp PROPERTIES RUN_SERIAL TRUE TIMEOUT 90
    ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=0;X2W_XMEM_PERMISSIVE=1;X2W_XMEM_GPU_MIRROR=0;X2W_XMEM_LAZY_COMMIT=0;X2W_XMEM_SHARED_VIEWS=0")
set_tests_properties(startup_queue_page_batch_runs_warp PROPERTIES RUN_SERIAL TRUE TIMEOUT 90 SKIP_RETURN_CODE 77
    ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=0;X2W_XMEM_PERMISSIVE=1;X2W_XMEM_GPU_MIRROR=0;X2W_XMEM_LAZY_COMMIT=0;X2W_XMEM_SHARED_VIEWS=1")

# Closed lists stay submittable, also after their allocator's Reset (#1352).
add_executable(startup_list_resubmit tests/startup_list_resubmit.cpp)
target_compile_features(startup_list_resubmit PRIVATE cxx_std_17)
target_link_libraries(startup_list_resubmit PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_list_resubmit_${backend} COMMAND startup_list_resubmit ${backend})
    set_tests_properties(startup_list_resubmit_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
    # The same steps without the D3D12 debug layer: catches UMD faults that SDKLayers validation hides (#1876).
    add_test(NAME startup_list_resubmit_nodebug_${backend} COMMAND startup_list_resubmit ${backend})
    set_tests_properties(startup_list_resubmit_nodebug_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0")
    add_test(NAME startup_list_resubmit_nodebug_untracked_${backend} COMMAND startup_list_resubmit ${backend} untracked)
    set_tests_properties(startup_list_resubmit_nodebug_untracked_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0;X2W_TEST_SUBMIT_FENCE_FAIL=1")
    # The same steps when no submit fence can be created: nothing may be reset or reused.
    add_test(NAME startup_list_resubmit_untracked_${backend} COMMAND startup_list_resubmit ${backend} untracked)
    set_tests_properties(startup_list_resubmit_untracked_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1;X2W_TEST_SUBMIT_FENCE_FAIL=1")
endforeach()

add_executable(startup_upload_arena tests/startup_upload_arena.cpp)
target_compile_features(startup_upload_arena PRIVATE cxx_std_17)
target_include_directories(startup_upload_arena PRIVATE src)
target_link_libraries(startup_upload_arena PRIVATE d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_upload_arena_${backend} COMMAND startup_upload_arena ${backend})
    set_tests_properties(startup_upload_arena_${backend} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
endforeach()

# Upload arena payloads must survive an arena reset while the GPU waits on a fence (Refs #1758).
add_executable(startup_upload_lifetime tests/startup_upload_lifetime.cpp)
target_compile_features(startup_upload_lifetime PRIVATE cxx_std_17)
target_include_directories(startup_upload_lifetime PRIVATE src)
target_link_libraries(startup_upload_lifetime PRIVATE d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_upload_lifetime_${backend} COMMAND startup_upload_lifetime ${backend})
    set_tests_properties(startup_upload_lifetime_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
endforeach()

# Acceptance client for command-list slot 148, the upload allocation of the title's acceleration-structure builder
# (Refs #1758, #2216). It drives the real list and queue, reads A and B on their own submitted lists through list
# slot 43 and checks the fixture resolver x2w_d3d12_upload_gpu_address. A missing or refusing slot is a failure.
# Only a missing physical adapter skips (77).
add_executable(startup_slot148_acceptance tests/startup_slot148_acceptance.cpp)
target_compile_features(startup_slot148_acceptance PRIVATE cxx_std_17)
target_link_libraries(startup_slot148_acceptance PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_slot148_acceptance_${backend} COMMAND startup_slot148_acceptance ${backend})
    set_tests_properties(startup_slot148_acceptance_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
    add_test(NAME startup_slot148_acceptance_nodebug_${backend} COMMAND startup_slot148_acceptance ${backend})
    set_tests_properties(startup_slot148_acceptance_nodebug_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0")
    # The serialized-queue path, forced on adapters whose queues do make progress (Refs #2210). The pass line is
    # printed only on exit 0 and names the skipped held-phase observer reads.
    add_test(NAME startup_slot148_acceptance_serialized_${backend} COMMAND startup_slot148_acceptance ${backend})
    set_tests_properties(startup_slot148_acceptance_serialized_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        PASS_REGULAR_EXPRESSION "slot 148 acceptance passed with skips: held-phase observer reads"
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1;X2W_TEST_FORCE_SERIALIZED_QUEUES=1")
    add_test(NAME startup_slot148_acceptance_serialized_nodebug_${backend} COMMAND startup_slot148_acceptance ${backend})
    set_tests_properties(startup_slot148_acceptance_serialized_nodebug_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        PASS_REGULAR_EXPRESSION "slot 148 acceptance passed with skips: held-phase observer reads"
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0;X2W_TEST_FORCE_SERIALIZED_QUEUES=1")
endforeach()

add_executable(startup_resource_budget tests/startup_resource_budget.cpp)
target_include_directories(startup_resource_budget PRIVATE src)
target_compile_features(startup_resource_budget PRIVATE cxx_std_17)
target_link_libraries(startup_resource_budget PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    foreach(debug IN ITEMS 0 1)
        set(case startup_resource_budget_${backend}_debug${debug})
        set(budget_env "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=${debug}")
        add_test(NAME ${case} COMMAND startup_resource_budget ${backend})
        add_test(NAME ${case}_inline_control COMMAND startup_resource_budget ${backend} inline-control)
        set_tests_properties(${case} ${case}_inline_control PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77 ENVIRONMENT "${budget_env}")
        set_tests_properties(${case}_inline_control PROPERTIES
            PASS_REGULAR_EXPRESSION "FAIL: inline-control missed Release left buffer above baseline")
    endforeach()
endforeach()

# X2W_D3D12_RELEASE_RETIRED=1 frees the desktop object of a committed 2D texture only when no recorded list, no submission
# and no release-time fence still refers to it (docs/startup-runtime.md#d3d12-resource-budget). The `off` case runs
# without the switch and expects the lifetime of the budget fixture: every released resource stays retained.
add_executable(startup_resource_retire tests/startup_resource_retire.cpp)
target_include_directories(startup_resource_retire PRIVATE src)
target_compile_features(startup_resource_retire PRIVATE cxx_std_17)
target_link_libraries(startup_resource_retire PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    foreach(debug IN ITEMS 0 1)
        set(retire_env "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=${debug}")
        add_test(NAME startup_resource_retire_${backend}_debug${debug} COMMAND startup_resource_retire ${backend})
        set_tests_properties(startup_resource_retire_${backend}_debug${debug} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "${retire_env};X2W_D3D12_RELEASE_RETIRED=1")
    endforeach()
    add_test(NAME startup_resource_retire_off_${backend} COMMAND startup_resource_retire ${backend} off)
    set_tests_properties(startup_resource_retire_off_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0")
endforeach()

# X2W_D3D12_RETIRE_REASONS=1 names why released resources still hold their desktop object (needs RELEASE_RETIRED and
# BUDGET). `off` (no RETIRE_REASONS) and `no-retire` (no RELEASE_RETIRED) are negative controls: the line must stay empty.
add_executable(startup_resource_retire_reasons tests/startup_resource_retire_reasons.cpp)
target_include_directories(startup_resource_retire_reasons PRIVATE src)
target_compile_features(startup_resource_retire_reasons PRIVATE cxx_std_17)
target_link_libraries(startup_resource_retire_reasons PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    set(reasons_base "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0")
    add_test(NAME startup_resource_retire_reasons_${backend} COMMAND startup_resource_retire_reasons ${backend})
    set_tests_properties(startup_resource_retire_reasons_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "${reasons_base};X2W_D3D12_RELEASE_RETIRED=1;X2W_D3D12_RETIRE_REASONS=1")
    add_test(NAME startup_resource_retire_reasons_off_${backend} COMMAND startup_resource_retire_reasons ${backend} off)
    set_tests_properties(startup_resource_retire_reasons_off_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "${reasons_base};X2W_D3D12_RELEASE_RETIRED=1")
    add_test(NAME startup_resource_retire_reasons_no_retire_${backend} COMMAND startup_resource_retire_reasons ${backend} no-retire)
    set_tests_properties(startup_resource_retire_reasons_no_retire_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "${reasons_base};X2W_D3D12_RETIRE_REASONS=1")
endforeach()


# X2W_D3D12_VIEW_CENSUS=1 counts new distinct view records by slot and logs capacity and buckets before they grow.
# `off` runs without the switch (nothing reported); `vary` is the negative control: the repeated stream is made distinct,
# and the fixture must say so.
add_executable(startup_view_census tests/startup_view_census.cpp)
target_compile_features(startup_view_census PRIVATE cxx_std_17)
target_link_libraries(startup_view_census PRIVATE d3d12_xs_shim d3d12 dxgi psapi)
foreach(backend IN ITEMS warp hardware)
    foreach(mode IN ITEMS on off vary)
        set(census_env "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0")
        list(APPEND census_env "X2W_TRAP_LOG=${CMAKE_CURRENT_BINARY_DIR}/startup_view_census_${mode}_${backend}.log")
        if(NOT mode STREQUAL "off")
            list(APPEND census_env "X2W_D3D12_VIEW_CENSUS=1")
        endif()
        if(mode STREQUAL "on")
            set(census_test startup_view_census_${backend})
            add_test(NAME ${census_test} COMMAND startup_view_census ${backend})
        else()
            set(census_test startup_view_census_${mode}_${backend})
            add_test(NAME ${census_test} COMMAND startup_view_census ${backend} ${mode})
        endif()
        set_tests_properties(${census_test} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77 ENVIRONMENT "${census_env}")
        if(mode STREQUAL "vary")
            set_tests_properties(${census_test} PROPERTIES
                PASS_REGULAR_EXPRESSION "FAIL: the repeated stream added records")
        endif()
    endforeach()
endforeach()

# #2653: a failed wrapper allocation returns E_OUTOFMEMORY with a null output from device creation and slots 8, 9, 14,
# 16, 55, 73, 127 and both paths through slot 133. `control` never arms the failure.
add_executable(startup_wrap_allocation tests/startup_wrap_allocation.cpp)
target_compile_features(startup_wrap_allocation PRIVATE cxx_std_17)
target_link_libraries(startup_wrap_allocation PRIVATE d3d12_xs_shim d3d12 dxgi)
add_test(NAME startup_wrap_allocation_warp COMMAND startup_wrap_allocation)
add_test(NAME startup_wrap_allocation_control_warp COMMAND startup_wrap_allocation control)
set_tests_properties(startup_wrap_allocation_warp startup_wrap_allocation_control_warp PROPERTIES
    TIMEOUT 60 SKIP_RETURN_CODE 77 ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=0")
set_tests_properties(startup_wrap_allocation_control_warp PROPERTIES
    PASS_REGULAR_EXPRESSION "FAIL: Device::slot55 derived pipeline with the wrapper allocation failing")

add_executable(startup_resource_retire_title tests/startup_resource_retire_title.cpp)
target_include_directories(startup_resource_retire_title PRIVATE src)
target_compile_features(startup_resource_retire_title PRIVATE cxx_std_17)
target_link_libraries(startup_resource_retire_title PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    foreach(debug IN ITEMS 0 1)
        set(retire_title_env "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_RESOURCE_INDEX_CHECK=1;X2W_D3D12_DEBUG=${debug}")
        add_test(NAME startup_resource_retire_title_${backend}_debug${debug} COMMAND startup_resource_retire_title ${backend})
        set_tests_properties(startup_resource_retire_title_${backend}_debug${debug} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "${retire_title_env};X2W_D3D12_RELEASE_RETIRED=1")
    endforeach()
    add_test(NAME startup_resource_retire_title_off_${backend} COMMAND startup_resource_retire_title ${backend} off)
    set_tests_properties(startup_resource_retire_title_off_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_RESOURCE_INDEX_CHECK=1;X2W_D3D12_DEBUG=0")
endforeach()

# Preserve live SRVs and their copies with and without the legacy views switch. Also verify that an
# explicit overwrite permits ordinary retirement, and that disabling base retirement keeps the resource.
add_executable(startup_resource_retire_views tests/startup_resource_retire_views.cpp)
target_include_directories(startup_resource_retire_views PRIVATE src)
target_compile_features(startup_resource_retire_views PRIVATE cxx_std_17)
target_link_libraries(startup_resource_retire_views PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    foreach(debug IN ITEMS 0 1)
        set(retire_views_env "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=${debug}")
        add_test(NAME startup_resource_retire_views_${backend}_debug${debug} COMMAND startup_resource_retire_views ${backend})
        set_tests_properties(startup_resource_retire_views_${backend}_debug${debug} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "${retire_views_env};X2W_D3D12_RELEASE_RETIRED=1;X2W_D3D12_RELEASE_RETIRED_VIEWS=1")
    endforeach()
    set(retire_views_keep "X2W_D3D12_BUDGET=1;X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=0")
    add_test(NAME startup_resource_retire_views_keep_${backend} COMMAND startup_resource_retire_views ${backend})
    set_tests_properties(startup_resource_retire_views_keep_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "${retire_views_keep};X2W_D3D12_RELEASE_RETIRED=1")
    add_test(NAME startup_resource_retire_views_noretire_${backend} COMMAND startup_resource_retire_views ${backend} keep)
    set_tests_properties(startup_resource_retire_views_noretire_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "${retire_views_keep};X2W_D3D12_RELEASE_RETIRED_VIEWS=1")
endforeach()

# GPU writes the dispatch record that the desktop command processor consumes (Refs #1412).
add_executable(startup_compute_binding_trace tests/startup_compute_binding_trace.cpp)
target_compile_features(startup_compute_binding_trace PRIVATE cxx_std_20)
target_link_libraries(startup_compute_binding_trace PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)

add_executable(startup_indirect_dispatch tests/startup_indirect_dispatch.cpp tests/desktop_gpu.cpp)
target_compile_features(startup_indirect_dispatch PRIVATE cxx_std_17)
target_link_libraries(startup_indirect_dispatch PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_indirect_dispatch_${backend} COMMAND startup_indirect_dispatch ${backend})
    add_test(NAME startup_indirect_root_constants_${backend} COMMAND startup_indirect_dispatch ${backend} constants)
    add_test(NAME startup_indirect_count_${backend} COMMAND startup_indirect_dispatch ${backend} count)
    # The same cases with the opt-in split of a batched or counted Dispatch into single commands
    # (split_indirect_dispatch.h), plus the follow-up Dispatch and the pending-allocator reset. The plain count tests
    # keep the native call.
    add_test(NAME startup_indirect_count_split_${backend} COMMAND startup_indirect_dispatch ${backend} count)
    set_tests_properties(startup_indirect_count_split_${backend} PROPERTIES ENVIRONMENT "X2W_SPLIT_INDIRECT_DISPATCH=1")
    set_tests_properties(startup_indirect_dispatch_${backend} startup_indirect_root_constants_${backend} startup_indirect_count_${backend}
                         startup_indirect_count_split_${backend} PROPERTIES TIMEOUT 30)
endforeach()
set_tests_properties(startup_indirect_dispatch_hardware startup_indirect_root_constants_hardware startup_indirect_count_hardware
                     startup_indirect_count_split_hardware PROPERTIES SKIP_RETURN_CODE 77)

# Occlusion queries recorded through command-list slots 28 to 30 reach the readback buffer (#870).
add_executable(startup_list_queries tests/startup_list_queries.cpp tests/desktop_gpu.cpp)
target_compile_features(startup_list_queries PRIVATE cxx_std_17)
target_link_libraries(startup_list_queries PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_list_queries_${backend} COMMAND startup_list_queries ${backend})
    set_tests_properties(startup_list_queries_${backend} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
    # Negative control: without X2W_D3D12_QUERY_SLOTS=1 the slots stay no-ops and the buffer keeps its sentinel.
    add_test(NAME startup_list_queries_default_${backend}_control COMMAND startup_list_queries ${backend} default)
    set_tests_properties(startup_list_queries_default_${backend}_control PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77
        PASS_REGULAR_EXPRESSION "word 0: got 0xa5a5a5a5a5a5a5a5")
endforeach()

add_executable(startup_indirect_draw_indexed tests/startup_indirect_draw_indexed.cpp tests/desktop_gpu.cpp)
target_compile_features(startup_indirect_draw_indexed PRIVATE cxx_std_17)
target_include_directories(startup_indirect_draw_indexed PRIVATE src)
target_link_libraries(startup_indirect_draw_indexed PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_indirect_draw_indexed_${backend} COMMAND startup_indirect_draw_indexed ${backend})
    add_test(NAME startup_indirect_draw_${backend} COMMAND startup_indirect_draw_indexed ${backend} draw)
    add_test(NAME startup_indirect_translated_draw_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated)
    add_test(NAME startup_indirect_translated_refusal_census_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated-refusal-census)
    add_test(NAME startup_indirect_translated_targets_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated-targets)
    add_test(NAME startup_indirect_other_refusal_census_${backend} COMMAND startup_indirect_draw_indexed ${backend} indirect-other-refusal-census)
    add_test(NAME startup_indirect_copy_provenance_${backend} COMMAND startup_indirect_draw_indexed ${backend} copy-provenance)
    add_test(NAME startup_indirect_copy_provenance_off_${backend} COMMAND startup_indirect_draw_indexed ${backend} copy-provenance-off)
    add_test(NAME startup_indirect_translated_indexed_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated-indexed)
    add_test(NAME startup_indirect_translated_indexed_upload_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated-indexed-upload)
    add_test(NAME startup_indirect_translated_indexed_rect_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated-indexed-rect)
    add_test(NAME startup_indirect_translated_indexed_alias_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated-indexed-alias)
    add_test(NAME startup_indirect_translated_indexed_alias_off_${backend} COMMAND startup_indirect_draw_indexed ${backend} translated-indexed-alias-off)
    add_test(NAME startup_indirect_mesh_${backend} COMMAND startup_indirect_draw_indexed ${backend} mesh)
    add_test(NAME startup_indirect_mesh_console_${backend} COMMAND startup_indirect_draw_indexed ${backend} mesh-console)
    add_test(NAME startup_indirect_mesh_amplified_${backend} COMMAND startup_indirect_draw_indexed ${backend} mesh-amplified)
    add_test(NAME startup_indirect_mesh_xmem_arguments_${backend}
        COMMAND startup_indirect_draw_indexed ${backend} mesh-xmem-arguments)
    add_test(NAME startup_indirect_mesh_xmem_arguments_skip_wait_${backend}
        COMMAND startup_indirect_draw_indexed ${backend} mesh-xmem-arguments-skip-wait)
    set_tests_properties(startup_indirect_mesh_xmem_arguments_${backend} startup_indirect_mesh_xmem_arguments_skip_wait_${backend}
        PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77 ENVIRONMENT "X2W_MESH86_FIXTURE_XMEM=$<TARGET_FILE:xmem_shim>")
    add_test(NAME startup_indirect_rectlist_${backend} COMMAND startup_indirect_draw_indexed ${backend} rect)
    set_tests_properties(startup_indirect_draw_indexed_${backend} startup_indirect_draw_${backend}
        startup_indirect_rectlist_${backend} PROPERTIES TIMEOUT 30)
    set_tests_properties(startup_indirect_mesh_${backend} startup_indirect_mesh_console_${backend}
        startup_indirect_mesh_amplified_${backend} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_indirect_translated_draw_${backend}
        startup_indirect_translated_refusal_census_${backend}
        startup_indirect_translated_targets_${backend}
        startup_indirect_other_refusal_census_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_indirect_copy_provenance_${backend} startup_indirect_copy_provenance_off_${backend}
        PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_indirect_translated_indexed_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_indirect_translated_indexed_upload_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_indirect_translated_indexed_rect_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_indirect_translated_indexed_alias_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_indirect_translated_indexed_alias_off_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
endforeach()
set_tests_properties(startup_indirect_draw_indexed_hardware startup_indirect_draw_hardware
    startup_indirect_rectlist_hardware PROPERTIES SKIP_RETURN_CODE 77)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_indirect_mesh_request_${backend} COMMAND startup_indirect_draw_indexed ${backend} mesh)
    add_test(NAME startup_indirect_mesh_create_result_${backend} COMMAND startup_indirect_draw_indexed ${backend} mesh)
    set_tests_properties(startup_indirect_mesh_create_result_${backend} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_FIXED_MESH_CREATE_FIXTURE=1")
    set_tests_properties(startup_indirect_mesh_request_${backend} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_MESH_REQUEST_FIXTURE=1")
endforeach()
# Negative control for the x2w-render indirect line: one forwarded call too many must be reported as a mismatch.
add_test(NAME startup_indirect_counts_control_warp COMMAND startup_indirect_draw_indexed warp count-control)
# "got" is printed only for a mismatch, and the pattern holds the real counts. No semicolons: CMake would split it.
set_tests_properties(startup_indirect_counts_control_warp PROPERTIES TIMEOUT 30
    PASS_REGULAR_EXPRESSION "got +'x2w-render indirect: forwarded: drawindexed 3. refused graphics-pipeline: drawindexed 1. compute-pipeline: dispatch 1. placeholder-signature: other 1. other: drawindexed 3'")
# Negative control for the per-(key, reason) indirect-draw refusal census: replacing the second refusal on key 1
# with a valid draw must report the real total (5) and pair count (3) as a mismatch.
add_test(NAME startup_indirect_translated_refusal_census_control_warp
    COMMAND startup_indirect_draw_indexed warp translated-refusal-census-control)
set_tests_properties(startup_indirect_translated_refusal_census_control_warp PROPERTIES TIMEOUT 60
    PASS_REGULAR_EXPRESSION "got +'x2w-d3d12 indirect-draw refusals: total 5. distinct keys 3, distinct pairs 3 \\(overflow calls 0\\)'")
# Negative control for the per-(key, reason) ExecuteIndirect other-refusal census: replacing the second refusal on
# key 1 with a valid draw must report the real total (3) and pair count (2) as a mismatch.
add_test(NAME startup_indirect_other_refusal_census_control_warp
    COMMAND startup_indirect_draw_indexed warp indirect-other-refusal-census-control)
set_tests_properties(startup_indirect_other_refusal_census_control_warp PROPERTIES TIMEOUT 60
    PASS_REGULAR_EXPRESSION "got +'x2w-d3d12 indirect-other refusals: total 3. distinct keys 2, distinct pairs 2 \\(overflow calls 0\\)'")

# Teardown of the four per-device caches that keep desktop D3D12 objects (#2572): the built d3d12_xs.dll is
# loaded by explicit path, warmed through its own probe, then unloaded -- the caches must release what they
# own and the module must go -- and a second load is run in a child process that leaves the module loaded to
# process termination, where the caches must detach every owned reference (the shim reports it under
# X2W_TEARDOWN_REPORT, and X2W_TEARDOWN_NO_GUARD has to make that check fail). This check runs the built DLL
# itself, so unlike the Python-driven startup_* tests it needs no INTAKE_PYTHON guard.
add_executable(startup_teardown_unload tests/startup_teardown_unload.cpp)
target_compile_features(startup_teardown_unload PRIVATE cxx_std_17)
target_link_libraries(startup_teardown_unload PRIVATE d3d12 dxgi)
add_dependencies(startup_teardown_unload d3d12_xs_shim)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_teardown_unload_${backend} COMMAND startup_teardown_unload
             "$<TARGET_FILE:d3d12_xs_shim>" ${backend})
    set_tests_properties(startup_teardown_unload_${backend} PROPERTIES TIMEOUT 60
        PASS_REGULAR_EXPRESSION "startup_teardown_unload ${backend}: PASS")
endforeach()
set_tests_properties(startup_teardown_unload_hardware PROPERTIES SKIP_RETURN_CODE 77)

# OMSetRenderTargets with a single descriptor range, handles that hold no view, and a cleared copied descriptor.
add_executable(startup_rtv_bind tests/startup_rtv_bind.cpp)
target_compile_features(startup_rtv_bind PRIVATE cxx_std_17)
target_link_libraries(startup_rtv_bind PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_rtv_bind_${backend} COMMAND startup_rtv_bind ${backend})
    set_tests_properties(startup_rtv_bind_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
endforeach()

# CopyResource, ResolveSubresource and CopyBufferRegion on a recording list (slots 17, 19 and 15).
add_executable(startup_list_copy tests/startup_list_copy.cpp)
target_compile_features(startup_list_copy PRIVATE cxx_std_17)
target_link_libraries(startup_list_copy PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_list_copy_${backend} COMMAND startup_list_copy ${backend})
    set_tests_properties(startup_list_copy_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
endforeach()

# Validation of the whole-resource copies (src/startup_stubs/list_copy.h); the mutated runs are negative controls.
add_executable(startup_list_copy_check tests/startup_list_copy_check.cpp)
target_include_directories(startup_list_copy_check PRIVATE src)
target_compile_features(startup_list_copy_check PRIVATE cxx_std_17)
add_test(NAME startup_list_copy_validation COMMAND startup_list_copy_check)
foreach(mutation IN ITEMS overflow typeless samples)
    add_test(NAME startup_list_copy_validation_${mutation}_control COMMAND startup_list_copy_check --mutate ${mutation})
    set_tests_properties(startup_list_copy_validation_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()

# List slots 53/54/55: ClearUnorderedAccessViewUint/Float and DiscardResource, read back on the desktop device.
add_executable(startup_clear_uav tests/startup_clear_uav.cpp)
target_compile_features(startup_clear_uav PRIVATE cxx_std_17)
target_link_libraries(startup_clear_uav PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_clear_uav_${backend} COMMAND startup_clear_uav ${backend})
    set_tests_properties(startup_clear_uav_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
endforeach()

# Resource slot 10: GetDesc on console resource wrappers.
add_executable(startup_resource_desc tests/startup_resource_desc.cpp)
target_compile_features(startup_resource_desc PRIVATE cxx_std_17)
target_link_libraries(startup_resource_desc PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_resource_desc_${backend} COMMAND startup_resource_desc ${backend})
    set_tests_properties(startup_resource_desc_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
endforeach()

# List slot 51: ClearDepthStencilView on a console command list, read back on the desktop device.
add_executable(startup_clear_depth_stencil tests/startup_clear_depth_stencil.cpp)
target_compile_features(startup_clear_depth_stencil PRIVATE cxx_std_17)
target_link_libraries(startup_clear_depth_stencil PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_clear_depth_stencil_${backend} COMMAND startup_clear_depth_stencil ${backend})
    set_tests_properties(startup_clear_depth_stencil_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_LIST_NOOP=1;X2W_D3D12_RENDER=1;X2W_D3D12_DEBUG=1")
endforeach()

add_executable(startup_nv12_draw tests/startup_nv12_draw.cpp tests/desktop_gpu.cpp)
target_compile_features(startup_nv12_draw PRIVATE cxx_std_17)
target_include_directories(startup_nv12_draw PRIVATE src)
target_link_libraries(startup_nv12_draw PRIVATE startup_stub_xg_xs d3d12 dxgi d3dcompiler)
add_executable(startup_plane_refresh tests/startup_plane_refresh.cpp tests/desktop_gpu.cpp)
target_compile_features(startup_plane_refresh PRIVATE cxx_std_17)
target_include_directories(startup_plane_refresh PRIVATE src)
target_link_libraries(startup_plane_refresh PRIVATE d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_plane_refresh_${backend} COMMAND startup_plane_refresh)
    set_tests_properties(startup_plane_refresh_${backend} PROPERTIES
        ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${backend}" TIMEOUT 60 SKIP_RETURN_CODE 77)
    add_test(NAME startup_nv12_draw_${backend} COMMAND startup_nv12_draw)
    set_tests_properties(startup_nv12_draw_${backend} PROPERTIES
        ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${backend}" TIMEOUT 60 SKIP_RETURN_CODE 77)
endforeach()
# The same header without a GPU (src/startup_stubs/slice_footprints.h): accepted NV12 descriptions,
# re-read intervals and size cap, the footprint request and the bytes up to the end of the last row.
# The mutated run is the negative control.
add_executable(startup_slice_footprints_check tests/startup_slice_footprints_check.cpp)
target_include_directories(startup_slice_footprints_check PRIVATE src)
target_compile_features(startup_slice_footprints_check PRIVATE cxx_std_17)
add_test(NAME startup_slice_footprints COMMAND startup_slice_footprints_check)
add_test(NAME startup_slice_footprints_padded_control COMMAND startup_slice_footprints_check --mutate padded-last-row)
set_tests_properties(startup_slice_footprints_padded_control PROPERTIES WILL_FAIL TRUE)

find_program(DXC_EXECUTABLE dxc REQUIRED)
foreach(stage mesh vertex pixel)
    if(stage STREQUAL mesh)
        set(profile ms_6_5)
    elseif(stage STREQUAL vertex)
        set(profile vs_6_0)
    else()
        set(profile ps_6_0)
    endif()
    set(header "${CMAKE_CURRENT_BINARY_DIR}/xmem_mesh_root_srv_${stage}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" -T ${profile} -E ${stage}
        -Vn xmem_mesh_root_srv_${stage} -Fh "${header}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/xmem_mesh_root_srv.hlsl"
        DEPENDS tests/xmem_mesh_root_srv.hlsl VERBATIM)
    target_sources(xmem_section_lease_check PRIVATE "${header}")
endforeach()
target_include_directories(xmem_section_lease_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
if(EXISTS "${INTAKE_PYTHON}")
    add_test(NAME startup_mesh86_srv_proof COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mesh86_srv_proof_check.py"
        "${DXC_EXECUTABLE}" "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(startup_mesh86_srv_proof PROPERTIES TIMEOUT 60)
    add_test(NAME runtime_mesh86_cache_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mesh86_cache_cli_check.py")
    add_test(NAME startup_indirect_mesh_lease_warp_dual-trace-disabled COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_indirect_mesh_cache_check.py"
        "${DXC_EXECUTABLE}" "$<TARGET_FILE:startup_indirect_draw_indexed>" warp
        "$<TARGET_FILE:xmem_shim>" dual-trace-disabled)
    set_tests_properties(startup_indirect_mesh_lease_warp_dual-trace-disabled PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    foreach(backend IN ITEMS warp hardware)
        add_test(NAME startup_indirect_mesh_lease_${backend}_dual-trace COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_indirect_mesh_cache_check.py"
            "${DXC_EXECUTABLE}" "$<TARGET_FILE:startup_indirect_draw_indexed>" ${backend}
            "$<TARGET_FILE:xmem_shim>" dual-trace)
        set_tests_properties(startup_indirect_mesh_lease_${backend}_dual-trace PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_indirect_mesh_cache_${backend} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_indirect_mesh_cache_check.py"
            "${DXC_EXECUTABLE}" "$<TARGET_FILE:startup_indirect_draw_indexed>" ${backend})
        set_tests_properties(startup_indirect_mesh_cache_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        foreach(mode IN ITEMS ordered_control skip-wait dual dual-skip-srv dual-skip-argument dual-init-only loose-root)
            set(test_name startup_indirect_mesh_lease_${backend}_${mode})
            add_test(NAME ${test_name} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_indirect_mesh_cache_check.py"
                "${DXC_EXECUTABLE}" "$<TARGET_FILE:startup_indirect_draw_indexed>" ${backend}
                "$<TARGET_FILE:xmem_shim>" ${mode})
            set_tests_properties(${test_name} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        endforeach()
    endforeach()
endif()
foreach(stage IN ITEMS mesh amplify amplified_mesh pixel)
    if(stage STREQUAL mesh OR stage STREQUAL amplified_mesh)
        set(profile ms_6_5)
    elseif(stage STREQUAL amplify)
        set(profile as_6_5)
    else()
        set(profile ps_6_0)
    endif()
    set(header "${CMAKE_CURRENT_BINARY_DIR}/startup_indirect_mesh_${stage}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" -T ${profile} -E ${stage}
        -Vn startup_indirect_mesh_${stage} -Fh "${header}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_indirect_mesh.hlsl"
        DEPENDS tests/startup_indirect_mesh.hlsl VERBATIM)
    target_sources(startup_indirect_draw_indexed PRIVATE "${header}")
endforeach()
target_include_directories(startup_indirect_draw_indexed PRIVATE src "${CMAKE_CURRENT_BINARY_DIR}")
add_dependencies(startup_indirect_draw_indexed xmem_shim)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_mesh_xmem_writer_${backend} COMMAND startup_indirect_draw_indexed ${backend} mesh-lease-writer)
    set_tests_properties(startup_mesh_xmem_writer_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_MESH86_FIXTURE_XMEM=$<TARGET_FILE:xmem_shim>")
endforeach()
get_filename_component(DXC_BIN_DIR "${DXC_EXECUTABLE}" DIRECTORY)
target_compile_definitions(root_probe PRIVATE SDK_DXC_DIR=L"${DXC_BIN_DIR}/")
add_executable(offscreen_check tests/offscreen_check.cpp tests/compute_check.cpp tests/dxr_check.cpp tests/buffer_ops.cpp
    tests/descriptor_heap_paging.cpp)
target_sources(offscreen_check PRIVATE tests/spirv_window/readback.cpp tests/spirv_window/sampler_readback.cpp
    tests/spirv_window/compaction_readback.cpp tests/spirv_window/compare_sampler.cpp
    tests/spirv_window/raw_uav_dump.cpp)
# Two builds of one control shader that differ only in the sampler descriptor index source (#1115).
# The SV_DispatchThreadID build is the passing control; the SV_GroupID build is the recorded
# reproduction. Descriptor tables, shader model, output indexing and all three swaps stay identical.
set(sampler_index_dir "${CMAKE_CURRENT_BINARY_DIR}/sampler_index_control")
add_custom_command(OUTPUT "${sampler_index_dir}/dispatch_index_cs.h"
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${sampler_index_dir}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main -Vn sampler_index_dispatch_cs
            -Fh "${sampler_index_dir}/dispatch_index_cs.h"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/sampler_index_control.hlsl"
    DEPENDS tests/sampler_index_control.hlsl VERBATIM)
add_custom_command(OUTPUT "${sampler_index_dir}/group_index_cs.h"
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${sampler_index_dir}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main -D INDEX_FROM_GROUP_ID=1 -Vn sampler_index_group_cs
            -Fh "${sampler_index_dir}/group_index_cs.h"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/sampler_index_control.hlsl"
    DEPENDS tests/sampler_index_control.hlsl VERBATIM)
target_sources(offscreen_check PRIVATE tests/spirv_window/sampler_index_control.cpp
    "${sampler_index_dir}/dispatch_index_cs.h" "${sampler_index_dir}/group_index_cs.h")
target_include_directories(offscreen_check PRIVATE "${sampler_index_dir}")
# Record the compiler that produced both builds, so a reproduction can name it alongside the adapter.
execute_process(COMMAND "${DXC_EXECUTABLE}" --version
    OUTPUT_VARIABLE sampler_index_dxc_version OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
string(REGEX MATCH "[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+" sampler_index_dxc_version "${sampler_index_dxc_version}")
if(sampler_index_dxc_version)
    target_compile_definitions(offscreen_check PRIVATE "DXC_VERSION_STRING=\"${sampler_index_dxc_version}\"")
endif()
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME sampler_index_control_${adapter}
             COMMAND offscreen_check ${adapter} --sampler-index-control)
    set_tests_properties(sampler_index_control_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
endforeach()
target_compile_features(offscreen_check PRIVATE cxx_std_17)
# Link the production placement index into this fixture without adding a DLL export.
set_property(SOURCE src/startup_stubs/d3d12_xs_device.cpp APPEND PROPERTY COMPILE_OPTIONS /bigobj)
set(OFFSCREEN_AGILITY_620_DIR "" CACHE PATH "Agility SDK 1.620.2 x64 DLL directory for debug validation")
# offscreen_check and cpu_placed_dxr_provider compile this file with the same flags (default CRT, the
# desktop SDK headers), so they link one object set instead of compiling the 3,400-line file twice.
# With OFFSCREEN_AGILITY_620_DIR the fixture compiles against the Agility headers instead: it keeps its
# own copy below and the provider keeps its own. d3d12_xs_shim uses the static CRT and is not shared.
if(NOT OFFSCREEN_AGILITY_620_DIR)
    add_library(d3d12_xs_device_obj OBJECT src/startup_stubs/d3d12_xs_device.cpp)
    target_include_directories(d3d12_xs_device_obj PRIVATE src)
    target_compile_features(d3d12_xs_device_obj PRIVATE cxx_std_17)
    target_sources(offscreen_check PRIVATE $<TARGET_OBJECTS:d3d12_xs_device_obj>)
else()
    target_sources(offscreen_check PRIVATE src/startup_stubs/d3d12_xs_device.cpp)
endif()
target_link_libraries(offscreen_check PRIVATE d3d12 dxgi dxguid d3dcompiler user32 gdi32 x2w_build_rev)
target_include_directories(offscreen_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
if(OFFSCREEN_AGILITY_620_DIR)
    if(EXISTS "${OFFSCREEN_AGILITY_620_DIR}/sdk.nupkg")
        set(agility_headers "${CMAKE_CURRENT_BINARY_DIR}/agility-headers")
        file(ARCHIVE_EXTRACT INPUT "${OFFSCREEN_AGILITY_620_DIR}/sdk.nupkg" DESTINATION "${agility_headers}"
             PATTERNS "build/native/include/*.h")
        target_include_directories(offscreen_check BEFORE PRIVATE "${agility_headers}/build/native/include")
        target_include_directories(startup_indirect_draw_indexed BEFORE PRIVATE "${agility_headers}/build/native/include")
        target_include_directories(d3d12_xs_shim BEFORE PRIVATE "${agility_headers}/build/native/include")
        target_compile_definitions(d3d12_xs_shim PRIVATE X2W_MESH_XMEM_AGILITY_620)
    endif()
    foreach(dll IN ITEMS D3D12Core.dll d3d12SDKLayers.dll)
        configure_file("${OFFSCREEN_AGILITY_620_DIR}/${dll}" "${CMAKE_CURRENT_BINARY_DIR}/D3D12/${dll}" COPYONLY)
    endforeach()
    target_compile_definitions(offscreen_check PRIVATE OFFSCREEN_AGILITY_620)
    target_compile_definitions(startup_indirect_draw_indexed PRIVATE OFFSCREEN_AGILITY_620)
endif()
set(OFFSCREEN_WARP_DIR "" CACHE PATH "Directory containing an app-local x64 d3d10warp.dll (Microsoft.Direct3D.WARP)")
if(OFFSCREEN_WARP_DIR)
    # On the Windows 10 in-box runtime, WARP 1.0.22 reports DXR tier 1.2 but every ray query misses.
    # With the Agility SDK runtime the same WARP passes the DXR checks, so require both together.
    if(NOT OFFSCREEN_AGILITY_620_DIR)
        message(FATAL_ERROR "OFFSCREEN_WARP_DIR requires OFFSCREEN_AGILITY_620_DIR. "
                "An app-local WARP on the in-box D3D12 runtime gives wrong ray query results.")
    endif()
endif()
include(cmake/app_local_warp.cmake)
offscreen_app_local_warp("${OFFSCREEN_WARP_DIR}" "${CMAKE_CURRENT_BINARY_DIR}")
add_test(NAME app_local_warp_toggle COMMAND "${CMAKE_COMMAND}" "-DSOURCE_DIR=${CMAKE_SOURCE_DIR}"
    "-DWORK_DIR=${CMAKE_CURRENT_BINARY_DIR}/app_local_warp_check" -P "${CMAKE_SOURCE_DIR}/tests/app_local_warp_check.cmake")
foreach(stage IN ITEMS vs ps)
    string(TOUPPER "${stage}" entry)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/triangle_${stage}.h")
    set(binary "${CMAKE_CURRENT_BINARY_DIR}/triangle_${stage}.cso")
    add_custom_command(OUTPUT "${header}" "${binary}"
        COMMAND "${DXC_EXECUTABLE}" -T ${stage}_6_0 -E ${entry}Main -Vn triangle_${stage}
                -Fh "${header}" -Fo "${binary}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/triangle.hlsl"
        DEPENDS tests/triangle.hlsl VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
foreach(stage IN ITEMS vs ps)
    string(TOUPPER "${stage}" entry)
    set(flip_header "${CMAKE_CURRENT_BINARY_DIR}/triangle_${stage}_flip.h")
    add_custom_command(OUTPUT "${flip_header}"
        COMMAND "${DXC_EXECUTABLE}" -T ${stage}_6_0 -E ${entry}Main -DFLIP -Vn triangle_${stage}_flip
                -Fh "${flip_header}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/triangle.hlsl"
        DEPENDS tests/triangle.hlsl VERBATIM)
endforeach()
add_custom_target(triangle_headers DEPENDS
    "${CMAKE_CURRENT_BINARY_DIR}/triangle_vs.h"
    "${CMAKE_CURRENT_BINARY_DIR}/triangle_ps.h"
    "${CMAKE_CURRENT_BINARY_DIR}/triangle_vs_flip.h"
    "${CMAKE_CURRENT_BINARY_DIR}/triangle_ps_flip.h")
add_dependencies(offscreen_check triangle_headers)
foreach(stage IN ITEMS vs ps)
    string(TOUPPER "${stage}" entry)
    set(tex_header "${CMAKE_CURRENT_BINARY_DIR}/tex_quad_${stage}.h")
    add_custom_command(OUTPUT "${tex_header}"
        COMMAND "${DXC_EXECUTABLE}" -T ${stage}_6_0 -E ${entry}Main -Vn tex_quad_${stage}
                -Fh "${tex_header}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/tex_quad.hlsl"
        DEPENDS tests/tex_quad.hlsl VERBATIM)
endforeach()
set(ray_header "${CMAKE_CURRENT_BINARY_DIR}/ray_query.h")
set(pixel_vs "${CMAKE_CURRENT_BINARY_DIR}/pixel_aot_vs.h")
add_custom_command(OUTPUT "${pixel_vs}" COMMAND "${DXC_EXECUTABLE}" -T vs_6_0 -E main
    -Fh "${pixel_vs}" -Vn pixel_aot_vs "${CMAKE_CURRENT_SOURCE_DIR}/tests/pixel_aot_vs.hlsl"
    DEPENDS tests/pixel_aot_vs.hlsl VERBATIM)
set(pixel_vs_linear "${CMAKE_CURRENT_BINARY_DIR}/pixel_aot_vs_linear.h")
add_custom_command(OUTPUT "${pixel_vs_linear}" COMMAND "${DXC_EXECUTABLE}" -T vs_6_0 -E main -D PIXEL_MIP_LINEAR=1
    -Fh "${pixel_vs_linear}" -Vn pixel_aot_vs_linear "${CMAKE_CURRENT_SOURCE_DIR}/tests/pixel_aot_vs.hlsl"
    DEPENDS tests/pixel_aot_vs.hlsl VERBATIM)
target_sources(offscreen_check PRIVATE tests/pixel_aot_render.cpp tests/pixel_compare_render.cpp "${pixel_vs}"
    "${pixel_vs_linear}")
target_sources(offscreen_check PRIVATE tests/desktop_gpu.cpp tests/mesh_entry_draw.cpp tests/mesh_shadow_draw.cpp)
add_executable(meshlet_builder_check tests/meshlet_builder_check.cpp src/meshlet_builder.cpp)
target_include_directories(meshlet_builder_check PRIVATE src)
target_compile_features(meshlet_builder_check PRIVATE cxx_std_17)
add_test(NAME meshlet_builder COMMAND meshlet_builder_check)
set_tests_properties(meshlet_builder PROPERTIES TIMEOUT 30)

set(meshlet_pipeline_headers)
foreach(stage_spec IN ITEMS "as:as_6_5:ASMain" "ms:ms_6_5:MSMain" "vs:vs_6_0:VSMain" "ps:ps_6_0:PSMain")
    string(REPLACE ":" ";" stage_parts "${stage_spec}")
    list(GET stage_parts 0 stage_name)
    list(GET stage_parts 1 stage_profile)
    list(GET stage_parts 2 stage_entry)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/meshlet_pipeline_${stage_name}.h")
    add_custom_command(OUTPUT "${header}"
        COMMAND "${DXC_EXECUTABLE}" -T ${stage_profile} -E ${stage_entry}
                -Vn meshlet_pipeline_${stage_name} -Fh "${header}"
                "${CMAKE_CURRENT_SOURCE_DIR}/src/shaders/meshlet_pipeline.hlsl"
        DEPENDS src/shaders/meshlet_pipeline.hlsl VERBATIM)
    list(APPEND meshlet_pipeline_headers "${header}")
endforeach()
target_sources(offscreen_check PRIVATE src/meshlet_builder.cpp src/mesh_shader_pipeline.cpp
    tests/mesh_shader_pipeline_draw.cpp ${meshlet_pipeline_headers})
target_include_directories(offscreen_check PRIVATE src)
target_sources(offscreen_check PRIVATE tests/stream_root_srv.cpp)
foreach(stage IN ITEMS vs ps)
    string(TOUPPER "${stage}" entry)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/stream_root_srv_${stage}.h")
    add_custom_command(OUTPUT "${header}"
        COMMAND "${DXC_EXECUTABLE}" -T ${stage}_6_0 -E ${entry}Main -Vn stream_root_srv_${stage}
                -Fh "${header}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/stream_root_srv.hlsl"
        DEPENDS tests/stream_root_srv.hlsl VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
set(descriptor_window_cs "${CMAKE_CURRENT_BINARY_DIR}/descriptor_window_submissions_cs.h")
add_custom_command(OUTPUT "${descriptor_window_cs}" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main
    -Vn descriptor_window_submissions_cs -Fh "${descriptor_window_cs}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/descriptor_window_submissions.hlsl"
    DEPENDS tests/descriptor_window_submissions.hlsl VERBATIM)
target_sources(offscreen_check PRIVATE tests/descriptor_window_submissions.cpp "${descriptor_window_cs}")
set(cpu_srv_cs "${CMAKE_CURRENT_BINARY_DIR}/cpu_srv_refresh_cs.h")
add_custom_command(OUTPUT "${cpu_srv_cs}" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main
    -Vn cpu_srv_refresh_cs -Fh "${cpu_srv_cs}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu_srv_refresh.hlsl"
    DEPENDS tests/cpu_srv_refresh.hlsl VERBATIM)
target_sources(offscreen_check PRIVATE "${cpu_srv_cs}")
# Argument, resource, fence and partial-read refusals and the Map/Unmap ranges of cpu_srv::refresh
# (src/cpu_srv_upload.h), with a fake upload buffer and fence instead of a device. The mutated run
# is the negative control.
add_executable(cpu_srv_upload_check tests/cpu_srv_upload_check.cpp)
target_include_directories(cpu_srv_upload_check PRIVATE src)
target_compile_features(cpu_srv_upload_check PRIVATE cxx_std_17)
add_test(NAME cpu_srv_upload COMMAND cpu_srv_upload_check)
add_test(NAME cpu_srv_upload_written_range_control COMMAND cpu_srv_upload_check --mutate written-range)
set_tests_properties(cpu_srv_upload_written_range_control PROPERTIES WILL_FAIL TRUE)
# Sampler word 1 LOD limits through the startup stand-in's decoder (#2221).
foreach(stage IN ITEMS vs ps)
    set(startup_sampler_lod_${stage} "${CMAKE_CURRENT_BINARY_DIR}/startup_sampler_lod_${stage}.h")
    add_custom_command(OUTPUT "${startup_sampler_lod_${stage}}" COMMAND "${DXC_EXECUTABLE}" -T ${stage}_6_0
        -E ${stage}_main -Vn startup_sampler_lod_${stage} -Fh "${startup_sampler_lod_${stage}}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_sampler_lod.hlsl"
        DEPENDS tests/startup_sampler_lod.hlsl VERBATIM)
    target_sources(offscreen_check PRIVATE "${startup_sampler_lod_${stage}}")
endforeach()
target_sources(offscreen_check PRIVATE tests/startup_sampler_lod.cpp)
set(startup_sampler_x_cs "${CMAKE_CURRENT_BINARY_DIR}/startup_sampler_x_cs.h")
add_custom_command(OUTPUT "${startup_sampler_x_cs}" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main
    -Vn startup_sampler_x_cs -Fh "${startup_sampler_x_cs}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_sampler_x.hlsl"
    DEPENDS tests/startup_sampler_x.hlsl VERBATIM)
target_sources(offscreen_check PRIVATE tests/startup_sampler_x.cpp "${startup_sampler_x_cs}")
target_sources(offscreen_check PRIVATE tests/startup_sampler_heap.cpp tests/mesh_heap_sampler_draw.cpp)
# Sampler word decoding, manifest lines and title sampler snapshots behind those draws
# (src/startup_stubs/translated_sampler_bindings.h), without a device. The mutated run is the negative control.
add_executable(startup_translated_sampler_bindings_check tests/startup_translated_sampler_bindings_check.cpp)
target_include_directories(startup_translated_sampler_bindings_check PRIVATE src)
target_compile_features(startup_translated_sampler_bindings_check PRIVATE cxx_std_17)
add_test(NAME startup_translated_sampler_bindings COMMAND startup_translated_sampler_bindings_check)
add_test(NAME startup_translated_sampler_bindings_shared_axis_control
    COMMAND startup_translated_sampler_bindings_check --mutate shared-axis)
set_tests_properties(startup_translated_sampler_bindings_shared_axis_control PROPERTIES WILL_FAIL TRUE)
# Real-draw decision for title root signatures that index descriptor heaps directly
# (src/startup_stubs/heap_indexed_root.h), without a device. The mutated runs are the negative controls.
# Limits of the slot 70 refusal and "token" null census (src/startup_stubs/memory_srv_census.h), without a device.
add_executable(startup_memory_srv_census_check tests/startup_memory_srv_census_check.cpp)
target_include_directories(startup_memory_srv_census_check PRIVATE src)
target_compile_features(startup_memory_srv_census_check PRIVATE cxx_std_17)
add_test(NAME startup_memory_srv_census COMMAND startup_memory_srv_census_check)
# Bounded per-(key, reason) refusal census (src/startup_stubs/per_reason_refusal_census.h), without a device.
# Both compile-time mutated targets build the real class with one reason per key and must fail.
add_executable(startup_per_reason_refusal_census_check tests/startup_per_reason_refusal_census_check.cpp)
target_include_directories(startup_per_reason_refusal_census_check PRIVATE src)
target_compile_features(startup_per_reason_refusal_census_check PRIVATE cxx_std_17)
add_test(NAME startup_per_reason_refusal_census COMMAND startup_per_reason_refusal_census_check)
foreach(mutation IN ITEMS keep_last keep_first)
    string(REPLACE "_" "-" mutation_flag ${mutation})
    string(TOUPPER "${mutation}" mutation_macro)
    add_executable(startup_per_reason_refusal_census_${mutation}_control tests/startup_per_reason_refusal_census_check.cpp)
    target_include_directories(startup_per_reason_refusal_census_${mutation}_control PRIVATE src)
    target_compile_features(startup_per_reason_refusal_census_${mutation}_control PRIVATE cxx_std_17)
    target_compile_definitions(startup_per_reason_refusal_census_${mutation}_control PRIVATE "X2W_CENSUS_${mutation_macro}")
    add_test(NAME startup_per_reason_refusal_census_${mutation_flag}_control
        COMMAND startup_per_reason_refusal_census_${mutation}_control)
    set_tests_properties(startup_per_reason_refusal_census_${mutation_flag}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
add_executable(startup_heap_indexed_root_check tests/startup_heap_indexed_root_check.cpp)
target_include_directories(startup_heap_indexed_root_check PRIVATE src)
target_compile_features(startup_heap_indexed_root_check PRIVATE cxx_std_17)
add_test(NAME startup_heap_indexed_root COMMAND startup_heap_indexed_root_check)
foreach(mutation IN ITEMS sampler-alone bind-unrestorable)
    add_test(NAME startup_heap_indexed_root_${mutation}_control COMMAND startup_heap_indexed_root_check --mutate ${mutation})
    set_tests_properties(startup_heap_indexed_root_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# Slot 14 (Dispatch) forward-or-refuse decision (src/startup_stubs/list_dispatch.h), without a device.
add_executable(startup_list_dispatch_check tests/startup_list_dispatch_check.cpp)
target_include_directories(startup_list_dispatch_check PRIVATE src)
target_compile_features(startup_list_dispatch_check PRIVATE cxx_std_17)
add_test(NAME startup_list_dispatch COMMAND startup_list_dispatch_check)
foreach(mutation IN ITEMS no-limit no-state no-root-args no-pairing no-bound)
    add_test(NAME startup_list_dispatch_${mutation}_control COMMAND startup_list_dispatch_check --mutate ${mutation})
    set_tests_properties(startup_list_dispatch_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
add_executable(upload_reservation_check tests/upload_reservation_check.cpp)
target_include_directories(upload_reservation_check PRIVATE src)
target_compile_features(upload_reservation_check PRIVATE cxx_std_17)
add_test(NAME upload_reservation COMMAND upload_reservation_check)
# The same slot driven through the stand-in on a desktop device: one refusal line per refused case, and the
# forwarded calls counted by a pipeline-statistics query on the desktop list.
add_executable(startup_list_dispatch_native tests/startup_list_dispatch_native.cpp)
target_compile_features(startup_list_dispatch_native PRIVATE cxx_std_17)
target_link_libraries(startup_list_dispatch_native PRIVATE d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_list_dispatch_native_${backend} COMMAND startup_list_dispatch_native ${backend})
    set_tests_properties(startup_list_dispatch_native_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
endforeach()
# Negative control: without slot 43 the first forwarded case is refused, and the fixture must report it.
add_test(NAME startup_list_dispatch_native_skip_srv_warp_control COMMAND startup_list_dispatch_native warp skip-srv)
set_tests_properties(startup_list_dispatch_native_skip_srv_warp_control PROPERTIES TIMEOUT 60
    PASS_REGULAR_EXPRESSION "bound: expected no Dispatch line, got 1 Dispatch line\\(s\\)[\r\n]+  x2w-render Dispatch\\(2, 3, 1\\) refused: a compute root SRV is not bound")
target_sources(offscreen_check PRIVATE tests/startup_image_3d.cpp)
target_sources(offscreen_check PRIVATE tests/startup_image_store.cpp)
target_sources(offscreen_check PRIVATE tests/startup_flat_param.cpp)
target_sources(offscreen_check PRIVATE tests/startup_entry_words.cpp)
# The storage root handed to the executable ends in a separator and is never cut off
# (src/startup_stubs/storage_root.h); the mutated run is the negative control.
add_executable(startup_storage_root_check tests/startup_storage_root_check.cpp)
target_include_directories(startup_storage_root_check PRIVATE src)
target_compile_features(startup_storage_root_check PRIVATE cxx_std_17)
add_test(NAME startup_storage_root COMMAND startup_storage_root_check)
add_test(NAME startup_storage_root_separator_control COMMAND startup_storage_root_check --mutate separator)
set_tests_properties(startup_storage_root_separator_control PROPERTIES WILL_FAIL TRUE)
# Stand-in formats for packed targets the adapter cannot use (src/startup_stubs/packed_target_format.h).
add_executable(startup_packed_target_check tests/startup_packed_target_check.cpp)
target_include_directories(startup_packed_target_check PRIVATE src)
target_compile_features(startup_packed_target_check PRIVATE cxx_std_17)
add_test(NAME startup_packed_target COMMAND startup_packed_target_check)
foreach(mutation IN ITEMS stand-in array b565 sharedexp sharedexp-uav view tag)
    add_test(NAME startup_packed_target_${mutation}_control COMMAND startup_packed_target_check --mutate ${mutation})
    set_tests_properties(startup_packed_target_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
target_sources(offscreen_check PRIVATE tests/startup_sharedexp_target.cpp)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME startup_sharedexp_target_${adapter} COMMAND offscreen_check ${adapter} --startup-sharedexp-target)
    set_tests_properties(startup_sharedexp_target_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
endforeach()
# Presented planes (src/startup_stubs/present_planes.h): the plane record layout and the composite order
# on synthetic records. The control reads 0x40-byte records and composites plane 0 alone, and must FAIL.
add_executable(startup_present_planes tests/startup_present_planes_check.cpp)
target_include_directories(startup_present_planes PRIVATE src)
target_compile_features(startup_present_planes PRIVATE cxx_std_17)
add_test(NAME startup_present_planes COMMAND startup_present_planes)
add_test(NAME startup_present_planes_control COMMAND startup_present_planes --control)
set_tests_properties(startup_present_planes_control PROPERTIES PASS_REGULAR_EXPRESSION "FAIL: ")
# The window's plane composite (src/startup_stubs/plane_compositor.h) read back on WARP: a single-plane
# baseline, stacked planes with transparent, partly transparent and opaque overlays, and skipped repeats
# and empty records. The control then removes the overlays and passes only on "control ok:", printed when
# the baseline matched, every fence completed and the overlay-free picture differs from the stacked
# expectation in exactly the overlay cells. Any FAIL line (setup, fence, device removal, pixels) fails it.
add_executable(startup_present_composite_warp tests/startup_present_composite_warp.cpp)
target_include_directories(startup_present_composite_warp PRIVATE src)
target_compile_features(startup_present_composite_warp PRIVATE cxx_std_17)
target_link_libraries(startup_present_composite_warp PRIVATE d3d12 dxgi d3dcompiler)
add_test(NAME startup_present_composite_warp COMMAND startup_present_composite_warp)
add_test(NAME startup_present_composite_overlay_removed_control_warp COMMAND startup_present_composite_warp --control)
set_tests_properties(startup_present_composite_warp PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60)
set_tests_properties(startup_present_composite_overlay_removed_control_warp PROPERTIES SKIP_RETURN_CODE 77 TIMEOUT 60
    PASS_REGULAR_EXPRESSION "control ok: baseline matched" FAIL_REGULAR_EXPRESSION "FAIL: ")
# Static samplers built from smp and smpc manifest lines (src/startup_stubs/translated_sampler_bindings.h).
add_executable(startup_sampler_comparison_check tests/startup_sampler_comparison_check.cpp)
target_include_directories(startup_sampler_comparison_check PRIVATE src)
target_compile_features(startup_sampler_comparison_check PRIVATE cxx_std_17)
add_test(NAME startup_sampler_comparison COMMAND startup_sampler_comparison_check)
# Diagnostic line for a refused device slot 70 call (src/startup_stubs/memory_srv_report.h).
add_executable(startup_memory_srv_report_check tests/startup_memory_srv_report_check.cpp)
target_include_directories(startup_memory_srv_report_check PRIVATE src)
target_compile_features(startup_memory_srv_report_check PRIVATE cxx_std_17)
add_test(NAME startup_memory_srv_report COMMAND startup_memory_srv_report_check)

# View format of the window presenter's read of typeless textures (src/startup_stubs/present_view_format.h);
# the identity run is the old behaviour and the sRGB run is a wrong view; both are negative controls.
add_executable(startup_present_view_check tests/startup_present_view_check.cpp)
target_include_directories(startup_present_view_check PRIVATE src)
target_compile_features(startup_present_view_check PRIVATE cxx_std_17)
target_link_libraries(startup_present_view_check PRIVATE d3d12 dxgi d3dcompiler)
add_test(NAME startup_present_view COMMAND startup_present_view_check)
add_test(NAME startup_present_view_identity_control COMMAND startup_present_view_check --mutate identity)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME startup_present_view_${adapter} COMMAND startup_present_view_check ${adapter})
endforeach()
add_test(NAME startup_present_view_srgb_control COMMAND startup_present_view_check warp --mutate srgb)
set_tests_properties(startup_present_view_identity_control startup_present_view_srgb_control PROPERTIES WILL_FAIL TRUE)
set_tests_properties(startup_present_view_hardware PROPERTIES SKIP_RETURN_CODE 77)
# Buffer memory SRV validation for device slot 70 (src/startup_stubs/memory_srv_buffer.h); the mutated
# runs are negative controls.
add_executable(startup_memory_srv_buffer_check tests/startup_memory_srv_buffer_check.cpp)
target_include_directories(startup_memory_srv_buffer_check PRIVATE src)
target_compile_features(startup_memory_srv_buffer_check PRIVATE cxx_std_17)
add_test(NAME startup_memory_srv_buffer COMMAND startup_memory_srv_buffer_check)
foreach(mutation IN ITEMS height exact-fit first-32 unplaced-extent unplaced-covers unplaced-heap-limit)
    add_test(NAME startup_memory_srv_buffer_${mutation}_control COMMAND startup_memory_srv_buffer_check --mutate ${mutation})
    set_tests_properties(startup_memory_srv_buffer_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# Descriptor word 3 for formatted buffer loads (src/startup_stubs/buffer_format_word3.h); the mutated run must fail.
add_executable(startup_buffer_format_word3_check tests/startup_buffer_format_word3_check.cpp)
target_include_directories(startup_buffer_format_word3_check PRIVATE src)
target_compile_features(startup_buffer_format_word3_check PRIVATE cxx_std_17)
add_test(NAME startup_buffer_format_word3 COMMAND startup_buffer_format_word3_check)
add_test(NAME startup_buffer_format_word3_mapping_control COMMAND startup_buffer_format_word3_check --mutate mapping)
set_tests_properties(startup_buffer_format_word3_mapping_control PROPERTIES WILL_FAIL TRUE)
# Acceleration-structure memory SRV validation for device slot 70 (src/startup_stubs/memory_srv_as.h); the
# mutated runs are negative controls.
add_executable(startup_memory_srv_as_check tests/startup_memory_srv_as_check.cpp)
target_include_directories(startup_memory_srv_as_check PRIVATE src)
target_compile_features(startup_memory_srv_as_check PRIVATE cxx_std_17)
add_test(NAME startup_memory_srv_as COMMAND startup_memory_srv_as_check)
foreach(mutation IN ITEMS alignment state offset)
    add_test(NAME startup_memory_srv_as_${mutation}_control COMMAND startup_memory_srv_as_check --mutate ${mutation})
    set_tests_properties(startup_memory_srv_as_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# Volume memory SRV validation for device slot 70 (src/startup_stubs/address_texture.h); the mutated
# runs are negative controls.
add_executable(startup_memory_srv_volume_check tests/startup_memory_srv_volume_check.cpp)
target_include_directories(startup_memory_srv_volume_check PRIVATE src)
target_compile_features(startup_memory_srv_volume_check PRIVATE cxx_std_17)
add_test(NAME startup_memory_srv_volume COMMAND startup_memory_srv_volume_check)
foreach(mutation IN ITEMS layout 2d-view 3d-view mips-overflow)
    add_test(NAME startup_memory_srv_volume_${mutation}_control COMMAND startup_memory_srv_volume_check --mutate ${mutation})
    set_tests_properties(startup_memory_srv_volume_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# Console allocation sizes for depth-with-stencil and multisampled textures
# (src/startup_stubs/console_plane_size.h); the mutated run is the negative control.
add_executable(startup_plane_size_check tests/startup_plane_size_check.cpp)
target_include_directories(startup_plane_size_check PRIVATE src)
target_compile_features(startup_plane_size_check PRIVATE cxx_std_17)
add_test(NAME startup_plane_size COMMAND startup_plane_size_check)
add_test(NAME startup_plane_size_packed_control COMMAND startup_plane_size_check --mutate packed)
set_tests_properties(startup_plane_size_packed_control PROPERTIES WILL_FAIL TRUE)
# Device slot 41: the indirect argument types desktop D3D12 cannot create
# (src/startup_stubs/command_signature_filter.h); the mutated runs are negative controls.
add_executable(startup_command_signature_filter_check tests/startup_command_signature_filter_check.cpp)
target_include_directories(startup_command_signature_filter_check PRIVATE src)
target_compile_features(startup_command_signature_filter_check PRIVATE cxx_std_17)
add_test(NAME startup_command_signature_filter COMMAND startup_command_signature_filter_check)
foreach(mutation IN ITEMS off-by-one first-only)
    add_test(NAME startup_command_signature_filter_${mutation}_control COMMAND startup_command_signature_filter_check --mutate ${mutation})
    set_tests_properties(startup_command_signature_filter_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# Device slot 41 through the startup device wrapper with the debug layer on: a desktop-valid argument
# list is created, a console type gets the placeholder, and the debug layer reports no error for either.
add_executable(startup_command_signature tests/startup_command_signature.cpp)
target_compile_features(startup_command_signature PRIVATE cxx_std_17)
target_link_libraries(startup_command_signature PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(backend IN ITEMS warp hardware)
    add_test(NAME startup_command_signature_${backend} COMMAND startup_command_signature ${backend})
    set_tests_properties(startup_command_signature_${backend} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=1")
endforeach()
# GameInput stand-in timestamps: a performance-counter reading in microseconds without a product
# that wraps (src/startup_stubs/qpc_microseconds.h); the mutated run is the negative control.
add_executable(startup_qpc_microseconds_check tests/startup_qpc_microseconds_check.cpp)
target_include_directories(startup_qpc_microseconds_check PRIVATE src)
target_compile_features(startup_qpc_microseconds_check PRIVATE cxx_std_17)
add_test(NAME startup_qpc_microseconds COMMAND startup_qpc_microseconds_check)
add_test(NAME startup_qpc_microseconds_product_control COMMAND startup_qpc_microseconds_check --mutate product)
set_tests_properties(startup_qpc_microseconds_product_control PROPERTIES WILL_FAIL TRUE)
# XGameSaveReadBlobData caller-buffer layout and size-overflow/uint32_t guards
# (src/startup_stubs/save_blob_pack.h); the mutated run is the negative control.
add_executable(startup_save_blob_pack_check tests/startup_save_blob_pack_check.cpp)
target_include_directories(startup_save_blob_pack_check PRIVATE src)
target_compile_features(startup_save_blob_pack_check PRIVATE cxx_std_17)
add_test(NAME startup_save_blob_pack COMMAND startup_save_blob_pack_check)
add_test(NAME startup_save_blob_pack_legacy_size_control COMMAND startup_save_blob_pack_check --mutate legacy-size)
set_tests_properties(startup_save_blob_pack_legacy_size_control PROPERTIES WILL_FAIL TRUE)
# The blend patch a slot 55 derivation applies (src/startup_stubs/derived_blend.h): the last part-2
# record, its descriptor offset and bytes, and lists that are not whole records. The mutated run is
# the negative control.
add_executable(startup_derived_blend_check tests/startup_derived_blend_check.cpp)
target_include_directories(startup_derived_blend_check PRIVATE src)
target_compile_features(startup_derived_blend_check PRIVATE cxx_std_17)
add_test(NAME startup_derived_blend COMMAND startup_derived_blend_check)
add_test(NAME startup_derived_blend_first_wins_control COMMAND startup_derived_blend_check --mutate first-wins)
set_tests_properties(startup_derived_blend_first_wins_control PROPERTIES WILL_FAIL TRUE)
# The same rule through the device wrapper: allocation-info slots 25 and 108, then a placed texture
# (slot 133) over memory of the answered size.
add_executable(startup_plane_size_device_check tests/startup_plane_size_device_check.cpp)
target_compile_features(startup_plane_size_device_check PRIVATE cxx_std_17)
target_link_libraries(startup_plane_size_device_check PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME startup_plane_size_device_${adapter} COMMAND startup_plane_size_device_check ${adapter})
endforeach()
set_tests_properties(startup_plane_size_device_hardware PROPERTIES SKIP_RETURN_CODE 77)
# Committed buffers through the device wrapper (slot 127) on the default, upload and readback heaps:
# upload and readback must start in GENERIC_READ and COPY_DEST, which the Windows 10 runtime enforces.
# The mutated run asks for a 2D texture on an upload heap, which no runtime creates (negative control).
add_executable(startup_committed_heap_state_check tests/startup_committed_heap_state_check.cpp)
target_compile_features(startup_committed_heap_state_check PRIVATE cxx_std_17)
target_link_libraries(startup_committed_heap_state_check PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME startup_committed_heap_state_${adapter} COMMAND startup_committed_heap_state_check ${adapter})
endforeach()
add_test(NAME startup_committed_heap_state_upload_texture_control COMMAND startup_committed_heap_state_check warp --mutate upload-texture)
set_tests_properties(startup_committed_heap_state_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(startup_committed_heap_state_upload_texture_control PROPERTIES WILL_FAIL TRUE)
# Device slot 76 (desktop CreateCommittedResource argument order) through the device wrapper: a render
# target with a clear value and buffers on the default, upload and readback heaps. The control asks for a
# 2D texture on an upload heap, which no runtime creates, and must FAIL.
add_executable(startup_committed_slot76_check tests/startup_committed_slot76_check.cpp)
target_compile_features(startup_committed_slot76_check PRIVATE cxx_std_17)
target_link_libraries(startup_committed_slot76_check PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME startup_committed_slot76_${adapter} COMMAND startup_committed_slot76_check ${adapter})
endforeach()
set_tests_properties(startup_committed_slot76_hardware PROPERTIES SKIP_RETURN_CODE 77)
add_test(NAME startup_committed_slot76_control COMMAND startup_committed_slot76_check warp --control)
# Opt-in BC7 4 KiB standard surfaces (src/startup_stubs/bc7_4k_s.h): accepted descriptions, padded
# sizes, block order and detile; the mutated run (x-first bit order) is the negative control.
add_executable(startup_bc7_4k_s_check tests/startup_bc7_4k_s_check.cpp)
target_include_directories(startup_bc7_4k_s_check PRIVATE src)
target_compile_features(startup_bc7_4k_s_check PRIVATE cxx_std_17)
add_test(NAME startup_bc7_4k_s COMMAND startup_bc7_4k_s_check)
add_test(NAME startup_bc7_4k_s_x_first_control COMMAND startup_bc7_4k_s_check --mutate x-first)
set_tests_properties(startup_bc7_4k_s_x_first_control PROPERTIES WILL_FAIL TRUE)
# Descriptor heaps whose desktop CPU start is not an address get plain memory as the start the
# executable sees (src/startup_stubs/title_heap_memory.h); the mutated run is the negative control.
add_executable(startup_title_heap_check tests/startup_title_heap_check.cpp)
target_compile_features(startup_title_heap_check PRIVATE cxx_std_17)
target_link_libraries(startup_title_heap_check PRIVATE d3d12_xs_shim d3d12 dxgi)
add_test(NAME startup_title_heap COMMAND startup_title_heap_check)
add_test(NAME startup_title_heap_tags_control COMMAND startup_title_heap_check --mutate tags)
set_tests_properties(startup_title_heap_tags_control PROPERTIES WILL_FAIL TRUE)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME startup_title_heap_device_${adapter} COMMAND startup_title_heap_check ${adapter})
endforeach()
set_tests_properties(startup_title_heap_device_hardware PROPERTIES SKIP_RETURN_CODE 77)
# Blend state of slot 57 pipelines from state block A (src/startup_stubs/state_block_blend.h, #1216).
add_executable(startup_state_block_blend_check tests/startup_state_block_blend_check.cpp)
target_include_directories(startup_state_block_blend_check PRIVATE src)
target_compile_features(startup_state_block_blend_check PRIVATE cxx_std_17)
add_test(NAME startup_state_block_blend COMMAND startup_state_block_blend_check)
# Depth-stencil state of slot 57 pipelines from state block A (src/startup_stubs/pipeline_state_decode.h,
# #1999): hand-built register words and a synthetic block. The mutated run (words one word later) is the
# negative control.
add_executable(startup_pipeline_state_check tests/startup_pipeline_state_check.cpp)
target_include_directories(startup_pipeline_state_check PRIVATE src)
target_compile_features(startup_pipeline_state_check PRIVATE cxx_std_17)
add_test(NAME startup_pipeline_state COMMAND startup_pipeline_state_check)
add_test(NAME startup_pipeline_state_offset_control COMMAND startup_pipeline_state_check --mutate offset)
set_tests_properties(startup_pipeline_state_offset_control PROPERTIES WILL_FAIL TRUE)
# Mesh-pipeline layout (+0x004 == 6, fields 0x54 later): a mesh block read at the vertex offsets must fail.
add_test(NAME startup_pipeline_state_mesh_shift_control COMMAND startup_pipeline_state_check --mutate mesh-shift)
set_tests_properties(startup_pipeline_state_mesh_shift_control PROPERTIES WILL_FAIL TRUE)
# PA_SU_SC_MODE_CNTL value -> D3D12 cull, winding and fill (src/startup_stubs/rasterizer_state_decode.h, #1999 B).
# Device-free; each control reads one field wrongly and must fail.
add_executable(startup_rasterizer_decode_check tests/startup_rasterizer_decode_check.cpp)
target_include_directories(startup_rasterizer_decode_check PRIVATE src)
target_compile_features(startup_rasterizer_decode_check PRIVATE cxx_std_17)
add_test(NAME startup_rasterizer_decode COMMAND startup_rasterizer_decode_check)
foreach(mutation IN ITEMS face cull fill)
    add_test(NAME startup_rasterizer_decode_${mutation}_control COMMAND startup_rasterizer_decode_check --mutate ${mutation})
    set_tests_properties(startup_rasterizer_decode_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# X2W_DEPTH_STATE (src/startup_stubs/depth_state_apply.h): off takes nothing from the block, on takes a decodable one.
add_executable(startup_depth_state_check tests/startup_depth_state_check.cpp)
target_include_directories(startup_depth_state_check PRIVATE src)
target_compile_features(startup_depth_state_check PRIVATE cxx_std_17)
add_test(NAME startup_depth_state COMMAND startup_depth_state_check)
add_test(NAME startup_depth_state_switch_control COMMAND startup_depth_state_check --mutate switch)
set_tests_properties(startup_depth_state_switch_control PROPERTIES WILL_FAIL TRUE)
# Root table handles resolved against a logical view heap, and the records a translated draw reads
# from the window (src/startup_stubs/logical_view_table.h).
add_executable(startup_logical_view_table_check tests/startup_logical_view_table_check.cpp)
target_include_directories(startup_logical_view_table_check PRIVATE src)
target_compile_features(startup_logical_view_table_check PRIVATE cxx_std_17)
add_test(NAME startup_logical_view_table COMMAND startup_logical_view_table_check)
# Compute descriptor tables (command-list slot 35, src/startup_stubs/list_compute_root.h): a table at a nonzero
# descriptor offset, a wrong handle, clear on a different signature or a view heap change, range limit.
add_executable(startup_compute_root tests/startup_compute_root.cpp)
target_include_directories(startup_compute_root PRIVATE src)
target_compile_features(startup_compute_root PRIVATE cxx_std_17)
add_test(NAME startup_compute_root COMMAND startup_compute_root)
# Local switch, logging, and page-probe helpers (src/startup_stubs/local_log.h, #1149).
add_executable(startup_local_log_check tests/startup_local_log_check.cpp)
target_include_directories(startup_local_log_check PRIVATE src)
target_compile_features(startup_local_log_check PRIVATE cxx_std_17)
add_test(NAME startup_local_log COMMAND startup_local_log_check)
add_test(NAME startup_local_log_guard_drop_control COMMAND startup_local_log_check --mutate guard-drop)
set_tests_properties(startup_local_log_guard_drop_control PROPERTIES WILL_FAIL TRUE)
add_test(NAME startup_local_log_reopen_control COMMAND startup_local_log_check --mutate reopen)
set_tests_properties(startup_local_log_reopen_control PROPERTIES WILL_FAIL TRUE)
# Negative control: the same check built against a generated copy of trap.h whose append_log keeps a
# failed open forever. Only the two open-failure recovery cases may fail; the copy exists only in
# the test build.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/startup_stubs/trap.h" trap_log_text)
string(REPLACE "now + log_retry_ms));  // x2w-seam: failed-open" "~0ull >> 1));" trap_log_cache_text "${trap_log_text}")
if(trap_log_cache_text STREQUAL trap_log_text)
    message(FATAL_ERROR "trap.h lost the failed-open anchor used by startup_local_log_cache_failure_control")
endif()
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/trap_log_cache_failure/startup_stubs/trap.h" "${trap_log_cache_text}")
add_executable(startup_local_log_cache_failure_check tests/startup_local_log_check.cpp)
target_include_directories(startup_local_log_cache_failure_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/trap_log_cache_failure" src)
target_compile_features(startup_local_log_cache_failure_check PRIVATE cxx_std_17)
add_test(NAME startup_local_log_cache_failure_control COMMAND startup_local_log_cache_failure_check --mutate cache-failure)
set_tests_properties(startup_local_log_cache_failure_control PROPERTIES WILL_FAIL TRUE)
# The counting gate the stand-ins used before must let calls through again at the wrap point.
add_test(NAME startup_local_log_wrap_control COMMAND startup_local_log_check --mutate wrap)
set_tests_properties(startup_local_log_wrap_control PROPERTIES
    PASS_REGULAR_EXPRESSION "FAIL first_calls passes no call at the wrap point")
# Trap-by-default export macros and env switches (src/startup_stubs/trap.h, #1149).
add_executable(startup_trap_header_check tests/startup_trap_header_check.cpp)
target_include_directories(startup_trap_header_check PRIVATE src)
target_compile_features(startup_trap_header_check PRIVATE cxx_std_17)
add_test(NAME startup_trap_header COMMAND startup_trap_header_check)
add_test(NAME startup_trap_header_prefix_control COMMAND startup_trap_header_check --mutate prefix-match)
add_test(NAME startup_trap_header_precedence_control COMMAND startup_trap_header_check --mutate fail-first)
set_tests_properties(startup_trap_header_prefix_control startup_trap_header_precedence_control
    PROPERTIES WILL_FAIL TRUE)

# Colour-blend register decoding (src/startup_stubs/cb_blend.h, #1216): decoder table plus draws
# compared with a CPU model of the register fields.
set(startup_cb_blend_vs "${CMAKE_CURRENT_BINARY_DIR}/startup_cb_blend_vs.h")
set(startup_cb_blend_ps "${CMAKE_CURRENT_BINARY_DIR}/startup_cb_blend_ps.h")
add_custom_command(OUTPUT "${startup_cb_blend_vs}" COMMAND "${DXC_EXECUTABLE}" -T vs_6_0 -E vs_main
    -Vn startup_cb_blend_vs -Fh "${startup_cb_blend_vs}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_cb_blend.hlsl"
    DEPENDS tests/startup_cb_blend.hlsl VERBATIM)
add_custom_command(OUTPUT "${startup_cb_blend_ps}" COMMAND "${DXC_EXECUTABLE}" -T ps_6_0 -E ps_main
    -Vn startup_cb_blend_ps -Fh "${startup_cb_blend_ps}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_cb_blend.hlsl"
    DEPENDS tests/startup_cb_blend.hlsl VERBATIM)
target_sources(offscreen_check PRIVATE tests/startup_cb_blend.cpp "${startup_cb_blend_vs}" "${startup_cb_blend_ps}")
# The same decoder without a device (#1149): each factor value in each of the four factor slots,
# colour and alpha combine functions apart, refusal reasons, MIN / MAX per slot, the write mask and
# control_word. The mutated run (destination alpha left in its colour form) is the negative control.
add_executable(startup_cb_blend_check tests/startup_cb_blend_check.cpp)
target_include_directories(startup_cb_blend_check PRIVATE src)
target_compile_features(startup_cb_blend_check PRIVATE cxx_std_17)
add_test(NAME startup_cb_blend_decode COMMAND startup_cb_blend_check)
add_test(NAME startup_cb_blend_decode_dest_alpha_control COMMAND startup_cb_blend_check --mutate dest-alpha-colour)
set_tests_properties(startup_cb_blend_decode_dest_alpha_control PROPERTIES WILL_FAIL TRUE)
# Export write masks from a translated manifest (#1674), without a device. The mutated run applies the
# masks to a shared blend state without expanding it, so a mask on target 1 is lost.
add_executable(startup_export_write_mask_check tests/startup_export_write_mask_check.cpp)
target_include_directories(startup_export_write_mask_check PRIVATE src)
target_compile_features(startup_export_write_mask_check PRIVATE cxx_std_17)
add_test(NAME startup_export_write_mask COMMAND startup_export_write_mask_check)
add_test(NAME startup_export_write_mask_shared_blend_control COMMAND startup_export_write_mask_check --mutate shared-blend)
set_tests_properties(startup_export_write_mask_shared_blend_control PROPERTIES WILL_FAIL TRUE)
# Bound SRV format classification and 'd16srv' manifest parsing for D16 image_load (#2023).
add_executable(startup_d16_image_format_check tests/startup_d16_image_format_check.cpp)
target_include_directories(startup_d16_image_format_check PRIVATE src)
target_compile_features(startup_d16_image_format_check PRIVATE cxx_std_17)
add_test(NAME startup_d16_image_format COMMAND startup_d16_image_format_check)
add_test(NAME startup_d16_image_format_accept_uint_control COMMAND startup_d16_image_format_check --mutate accept-uint)
set_tests_properties(startup_d16_image_format_accept_uint_control PROPERTIES WILL_FAIL TRUE)
# Composite provenance (#1628): one VS and two pixel shaders from one HLSL file.
set(startup_composite_provenance_headers "")
foreach(stage IN ITEMS "vs_6_0;vs_main;vs" "ps_6_0;ps_fill;fill" "ps_6_0;ps_composite;composite")
    list(GET stage 0 profile)
    list(GET stage 1 entry)
    list(GET stage 2 suffix)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/startup_composite_provenance_${suffix}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" -T ${profile} -E ${entry}
        -Vn startup_composite_provenance_${suffix} -Fh "${header}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_composite_provenance.hlsl"
        DEPENDS tests/startup_composite_provenance.hlsl VERBATIM)
    list(APPEND startup_composite_provenance_headers "${header}")
endforeach()
target_sources(offscreen_check PRIVATE tests/startup_composite_provenance.cpp ${startup_composite_provenance_headers})
# Range provenance (#870): one VS, one consumer and one producer pixel shader from one HLSL file.
set(startup_range_provenance_headers "")
foreach(stage IN ITEMS "vs_6_0;vs_main;vs" "ps_6_0;ps_read;read" "ps_6_0;ps_write;write")
    list(GET stage 0 profile)
    list(GET stage 1 entry)
    list(GET stage 2 suffix)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/startup_range_provenance_${suffix}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" -T ${profile} -E ${entry}
        -Vn startup_range_provenance_${suffix} -Fh "${header}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_range_provenance.hlsl"
        DEPENDS tests/startup_range_provenance.hlsl VERBATIM)
    list(APPEND startup_range_provenance_headers "${header}")
endforeach()
target_sources(offscreen_check PRIVATE tests/startup_range_provenance.cpp ${startup_range_provenance_headers})
target_sources(offscreen_check PRIVATE tests/binding_mips.cpp tests/ffx_recurrent_views.cpp)
target_sources(offscreen_check PRIVATE tests/ffx_rcas_views.cpp)
foreach(storage IN ITEMS Native Packed)
    foreach(op IN ITEMS Read Write)
        set(symbol "Rcas${op}${storage}")
        set(header "${CMAKE_CURRENT_BINARY_DIR}/${symbol}.h")
        add_custom_command(OUTPUT "${header}"
            COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E "Rcas${op}" -D "STORAGE_${storage}=1"
                -Vn "${symbol}" -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${symbol}.cso"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/ffx_rcas.hlsl"
            DEPENDS tests/ffx_rcas.hlsl src/rgb9e5.hlsli BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${symbol}.cso" VERBATIM)
        target_sources(offscreen_check PRIVATE "${header}")
    endforeach()
endforeach()
foreach(entry IN ITEMS DualUav SampleMip WriteRecurrent DynamicSamplerIndex)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${entry}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E ${entry}
        -Vn ${entry} -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/binding_mips.hlsl" DEPENDS tests/binding_mips.hlsl
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso" VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
target_sources(offscreen_check PRIVATE tests/bvh_reads_waves.cpp tests/bvh_hits.cpp)
target_sources(offscreen_check PRIVATE tests/bvh_atomics.cpp tests/bvh_numeric.cpp)
# A title graphics allocation opened as a D3D12 heap and addressed through translated GPU addresses.
target_sources(offscreen_check PRIVATE tests/gpu_alias.cpp src/era_gpu_alias.cpp src/era_title_va.cpp src/era_heap.cpp)
# The same open without a GPU: spans it must refuse before calling D3D12, and spans that must reach
# the device, against a recording fake device. The control builds a generated copy of
# era_gpu_alias.cpp that no longer compares the allocation base, which the interior pointer must catch.
add_executable(era_gpu_alias_check tests/era_gpu_alias_check.cpp tests/era_gpu_alias_fake_device.cpp
    src/era_gpu_alias.cpp)
target_include_directories(era_gpu_alias_check PRIVATE src tests)
target_compile_features(era_gpu_alias_check PRIVATE cxx_std_17)
add_test(NAME era_gpu_alias_open COMMAND era_gpu_alias_check)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS src/era_gpu_alias.cpp)
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/era_gpu_alias.cpp" gpu_alias_text)
string(FIND "${gpu_alias_text}" "info.AllocationBase != base || " gpu_alias_anchor)
if(gpu_alias_anchor LESS 0)
    message(FATAL_ERROR "era_gpu_alias.cpp lost the anchor used by era_gpu_alias_open_base_control")
endif()
string(REPLACE "info.AllocationBase != base || " "" gpu_alias_text "${gpu_alias_text}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/gpu_alias_base_control/era_gpu_alias.cpp" "${gpu_alias_text}")
add_executable(era_gpu_alias_base_control_check tests/era_gpu_alias_check.cpp tests/era_gpu_alias_fake_device.cpp
    "${CMAKE_CURRENT_BINARY_DIR}/gpu_alias_base_control/era_gpu_alias.cpp")
target_include_directories(era_gpu_alias_base_control_check PRIVATE src tests)
target_compile_features(era_gpu_alias_base_control_check PRIVATE cxx_std_17)
add_test(NAME era_gpu_alias_open_base_control COMMAND era_gpu_alias_base_control_check)
set_tests_properties(era_gpu_alias_open_base_control PROPERTIES PASS_REGULAR_EXPRESSION
    "FAIL: interior pointer: passed to D3D12")
# A title buffer window: two 64 KiB pages, a non-page-aligned offset, copies in both directions and
# named rejects for an outside address, a misaligned page run and an uncommitted page.
target_sources(offscreen_check PRIVATE tests/gpu_alias_window.cpp)
# The same allocations read by a shader through 64-bit title addresses (src/title_va_lookup.hlsli).
target_sources(offscreen_check PRIVATE tests/depth_mask_draw.cpp)
target_sources(offscreen_check PRIVATE tests/gpu_alias_lookup.cpp)
# Graphics allocations given desktop GPU addresses when a device is attached (src/era_title_gpu.cpp).
target_sources(offscreen_check PRIVATE tests/gpu_alias_registry.cpp src/era_title_gpu.cpp src/era_query.cpp)
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/LookupTitleAddresses.h" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0
    -E LookupTitleAddresses -Vn LookupTitleAddresses -I "${CMAKE_CURRENT_SOURCE_DIR}/src"
    -Fh "${CMAKE_CURRENT_BINARY_DIR}/LookupTitleAddresses.h" -Fo "${CMAKE_CURRENT_BINARY_DIR}/LookupTitleAddresses.cso"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/gpu_alias_lookup.hlsl" DEPENDS tests/gpu_alias_lookup.hlsl src/title_va_lookup.hlsli
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/LookupTitleAddresses.cso" VERBATIM)
target_sources(offscreen_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/LookupTitleAddresses.h")
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/WriteTitleAddresses.h" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0
    -E WriteTitleAddresses -Vn WriteTitleAddresses -I "${CMAKE_CURRENT_SOURCE_DIR}/src"
    -Fh "${CMAKE_CURRENT_BINARY_DIR}/WriteTitleAddresses.h" -Fo "${CMAKE_CURRENT_BINARY_DIR}/WriteTitleAddresses.cso"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/gpu_alias_writes.hlsl" DEPENDS tests/gpu_alias_writes.hlsl src/title_va_lookup.hlsli
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/WriteTitleAddresses.cso" VERBATIM)
target_sources(offscreen_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/WriteTitleAddresses.h")
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomics.h" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0
    -E ProbeArrayAtomics -Vn ProbeArrayAtomics -I "${CMAKE_CURRENT_SOURCE_DIR}/src"
    -Fh "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomics.h" -Fo "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomics.cso"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/gpu_alias_writes.hlsl" DEPENDS tests/gpu_alias_writes.hlsl src/title_va_lookup.hlsli
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomics.cso" VERBATIM)
target_sources(offscreen_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomics.h")
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomicsWaterfall.h" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0
    -E ProbeArrayAtomicsWaterfall -Vn ProbeArrayAtomicsWaterfall
    -Fh "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomicsWaterfall.h"
    -Fo "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomicsWaterfall.cso"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/gpu_alias_atomic_waterfall.hlsl"
    DEPENDS tests/gpu_alias_atomic_waterfall.hlsl
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomicsWaterfall.cso" VERBATIM)
target_sources(offscreen_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomicsWaterfall.h")
target_include_directories(offscreen_check PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/AliasTransform.h" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0
    -E AliasTransform -Vn AliasTransform -Fh "${CMAKE_CURRENT_BINARY_DIR}/AliasTransform.h"
    -Fo "${CMAKE_CURRENT_BINARY_DIR}/AliasTransform.cso" "${CMAKE_CURRENT_SOURCE_DIR}/tests/gpu_alias.hlsl"
    DEPENDS tests/gpu_alias.hlsl BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/AliasTransform.cso" VERBATIM)
target_sources(offscreen_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/AliasTransform.h")
foreach(entry IN ITEMS InitBounds AtomicBounds QueryBounds NumericBounds)
    set(bounds_source tests/bvh_atomics.hlsl)
    if(entry STREQUAL "NumericBounds")
        set(bounds_source tests/bvh_numeric.hlsl)
    endif()
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${entry}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" -T cs_6_5 -E ${entry}
        -Vn ${entry} -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso"
        "${CMAKE_CURRENT_SOURCE_DIR}/${bounds_source}" DEPENDS "${bounds_source}"
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso" VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
foreach(entry IN ITEMS Produce ReadValues WaveValues Wave64 WriteScene ExpandLeaves TraceHits)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${entry}.h")
    set(wave_args -T cs_6_5 -E ${entry})
    if(entry STREQUAL "Wave64")
        set(wave_args -T cs_6_6 -E WaveValues -D REQUIRE_WAVE64=1)
    endif()
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" ${wave_args} -Vn ${entry}
        -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/bvh_reads_waves.hlsl" DEPENDS tests/bvh_reads_waves.hlsl
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso" VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
target_sources(offscreen_check PRIVATE tests/wave_shuffle.cpp)
foreach(width IN ITEMS 0 16 32 64)
    if(width)
        set(entry WaveShuffle${width})
        set(shuffle_args -T cs_6_6 -D WAVE_SIZE=${width})
    else()
        set(entry WaveShuffle)
        set(shuffle_args -T cs_6_5)
    endif()
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${entry}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" ${shuffle_args} -E Shuffle -Vn ${entry}
        -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/wave_shuffle.hlsl" DEPENDS tests/wave_shuffle.hlsl
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso" VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
# 64-lane wave operations emulated with group-shared memory (src/wave64_emulate.hlsli).
target_sources(offscreen_check PRIVATE tests/wave64_emulate.cpp)
foreach(entry IN ITEMS Wave64Emulate Wave64Emulate64 Wave64EmulateSkew)
    set(emulate_args -T cs_6_0)
    if(entry STREQUAL "Wave64Emulate64")
        set(emulate_args -T cs_6_6 -D WAVE_SIZE=64)
    elseif(entry STREQUAL "Wave64EmulateSkew")
        list(APPEND emulate_args -D SKEW=1)
    endif()
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${entry}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" ${emulate_args} -E Emulate -Vn ${entry}
        -I "${CMAKE_CURRENT_SOURCE_DIR}/src" -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/wave64_emulate.hlsl" DEPENDS tests/wave64_emulate.hlsl src/wave64_emulate.hlsli
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso" VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
target_sources(offscreen_check PRIVATE tests/shader_wave.cpp)
foreach(width IN ITEMS 0 32 64)
    if(width)
        set(entry ShaderWave${width})
        set(wave_args -T cs_6_6 -D WAVE_SIZE=${width})
    else()
        set(entry ShaderWave)
        set(wave_args -T cs_6_0)
    endif()
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${entry}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" ${wave_args} -E WaveWidth -Vn ${entry}
        -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/shader_wave.hlsl" DEPENDS tests/shader_wave.hlsl
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso" VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
foreach(entry IN ITEMS CopyBlocks FillBlocks NumberBlocks CopySpan ResetBounds)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${entry}.h")
    add_custom_command(OUTPUT "${header}" COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E ${entry} -Vn ${entry}
        -Fh "${header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/buffer_ops.hlsl" DEPENDS tests/buffer_ops.hlsl
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${entry}.cso" VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
endforeach()
add_custom_command(OUTPUT "${ray_header}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_5 -E CSMain -Vn ray_query -Fh "${ray_header}"
            -Fo "${CMAKE_CURRENT_BINARY_DIR}/ray_query.cso" "${CMAKE_CURRENT_SOURCE_DIR}/tests/ray_query.hlsl"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/ray_query.cso" DEPENDS tests/ray_query.hlsl VERBATIM)
set(ray_table_header "${CMAKE_CURRENT_BINARY_DIR}/ray_query_table.h")
add_custom_command(OUTPUT "${ray_table_header}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_5 -E CSMain -D AS_TABLE=1 -Vn ray_query_table -Fh "${ray_table_header}"
            -Fo "${CMAKE_CURRENT_BINARY_DIR}/ray_query_table.cso" "${CMAKE_CURRENT_SOURCE_DIR}/tests/ray_query.hlsl"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/ray_query_table.cso" DEPENDS tests/ray_query.hlsl VERBATIM)
set(ray_pipeline_header "${CMAKE_CURRENT_BINARY_DIR}/ray_pipeline.h")
add_custom_command(OUTPUT "${ray_pipeline_header}"
    COMMAND "${DXC_EXECUTABLE}" -T lib_6_3 -D DXR_PIPELINE=1 -Vn ray_pipeline -Fh "${ray_pipeline_header}"
            -Fo "${CMAKE_CURRENT_BINARY_DIR}/ray_pipeline.cso" "${CMAKE_CURRENT_SOURCE_DIR}/tests/ray_query.hlsl"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/ray_pipeline.cso" DEPENDS tests/ray_query.hlsl VERBATIM)
set(candidates_header "${CMAKE_CURRENT_BINARY_DIR}/ray_candidates.h")
add_custom_command(OUTPUT "${candidates_header}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_5 -E CSMain -Vn ray_candidates -Fh "${candidates_header}"
            -Fo "${CMAKE_CURRENT_BINARY_DIR}/ray_candidates.cso" "${CMAKE_CURRENT_SOURCE_DIR}/tests/ray_candidates.hlsl"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/ray_candidates.cso" DEPENDS tests/ray_candidates.hlsl VERBATIM)
set(candidates_pipeline_header "${CMAKE_CURRENT_BINARY_DIR}/ray_candidates_pipeline.h")
add_custom_command(OUTPUT "${candidates_pipeline_header}"
    COMMAND "${DXC_EXECUTABLE}" -T lib_6_3 -D DXR_PIPELINE=1 -Vn ray_candidates_pipeline -Fh "${candidates_pipeline_header}"
            -Fo "${CMAKE_CURRENT_BINARY_DIR}/ray_candidates_pipeline.cso" "${CMAKE_CURRENT_SOURCE_DIR}/tests/ray_candidates.hlsl"
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/ray_candidates_pipeline.cso" DEPENDS tests/ray_candidates.hlsl VERBATIM)
target_sources(offscreen_check PRIVATE "${ray_header}" "${ray_table_header}" "${ray_pipeline_header}" "${candidates_header}" "${candidates_pipeline_header}"
    tests/dxr_facing.cpp tests/dxr_opacity.cpp)
foreach(layout IN ITEMS root tables)
    set(header "${CMAKE_CURRENT_BINARY_DIR}/compute_${layout}.h")
    set(binary "${CMAKE_CURRENT_BINARY_DIR}/compute_${layout}.cso")
    set(defines)
    if(layout STREQUAL "tables")
        set(defines -D TABLE_BINDINGS=1)
    endif()
    add_custom_command(OUTPUT "${header}" "${binary}"
        COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E CSMain ${defines} -Vn compute_${layout}
                -Fh "${header}" -Fo "${binary}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compute.hlsl"
        DEPENDS tests/compute.hlsl VERBATIM)
    target_sources(offscreen_check PRIVATE "${header}")
    foreach(adapter IN ITEMS hardware warp)
        add_test(NAME compute_${layout}_${adapter} COMMAND offscreen_check ${adapter} --compute-${layout})
        set_tests_properties(compute_${layout}_${adapter} PROPERTIES TIMEOUT 45)
    endforeach()
    set_tests_properties(compute_${layout}_hardware PROPERTIES SKIP_RETURN_CODE 77)
endforeach()
# XBOX2WINDOWS_ADAPTER selects a hardware adapter by part of its name. A name no adapter has must fail.
add_test(NAME adapter_selection_unmatched COMMAND offscreen_check hardware --dual-uav)
set_tests_properties(adapter_selection_unmatched PROPERTIES TIMEOUT 45
    ENVIRONMENT "XBOX2WINDOWS_ADAPTER=no adapter has this name"
    PASS_REGULAR_EXPRESSION "No D3D12 hardware adapter matches XBOX2WINDOWS_ADAPTER=no adapter has this name")
add_executable(pso_root_check tests/pso_root_check.cpp)
target_compile_features(pso_root_check PRIVATE cxx_std_17)
target_include_directories(pso_root_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(pso_root_check PRIVATE d3d12 dxgi)
foreach(mode IN ITEMS embedded stripped)
    set(symbol pso_compute_${mode})
    set(header "${CMAKE_CURRENT_BINARY_DIR}/${symbol}.h")
    set(strip_root)
    if(mode STREQUAL "stripped")
        set(strip_root -Qstrip_rootsignature)
    endif()
    add_custom_command(OUTPUT "${header}"
        COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E CSMain ${strip_root} -Vn ${symbol}
                -Fh "${header}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compute.hlsl"
        DEPENDS tests/compute.hlsl VERBATIM)
    target_sources(pso_root_check PRIVATE "${header}")
endforeach()
add_test(NAME pso_root_signature_warp COMMAND pso_root_check)
add_custom_target(pso_compute_headers DEPENDS
    "${CMAKE_CURRENT_BINARY_DIR}/pso_compute_embedded.h"
    "${CMAKE_CURRENT_BINARY_DIR}/pso_compute_stripped.h")
foreach(stage IN ITEMS vs ps)
    string(TOUPPER "${stage}" entry)
    set(rect_header "${CMAKE_CURRENT_BINARY_DIR}/rectlist_${stage}.h")
    add_custom_command(OUTPUT "${rect_header}"
        COMMAND "${DXC_EXECUTABLE}" -T ${stage}_6_0 -E ${entry}Main -Vn rectlist_${stage}
                -Fh "${rect_header}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/rectlist_quad.hlsl"
        DEPENDS tests/rectlist_quad.hlsl VERBATIM)
    set(rectlist_shader_${stage} "${rect_header}")
endforeach()
add_custom_target(rectlist_headers DEPENDS
    "${rectlist_shader_vs}"
    "${rectlist_shader_ps}")
add_executable(rectlist_draw_check tests/rectlist_draw_check.cpp
    "${rectlist_shader_vs}"
    "${rectlist_shader_ps}")
add_dependencies(rectlist_draw_check rectlist_headers)
target_compile_features(rectlist_draw_check PRIVATE cxx_std_17)
target_include_directories(rectlist_draw_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(rectlist_draw_check PRIVATE d3d12 dxgi)
add_executable(d3d12_xs_shim_check tests/d3d12_xs_shim_check.cpp)
add_dependencies(d3d12_xs_shim_check pso_compute_headers)
target_link_libraries(d3d12_xs_shim_check PRIVATE d3d12_xs_shim dxgi)
target_include_directories(d3d12_xs_shim_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(d3d12_xs_shim_check PRIVATE cxx_std_17)
foreach(scenario IN ITEMS exports serialize deserialize iids warp_root heap_indexing)
    add_test(NAME d3d12_xs_shim_${scenario} COMMAND d3d12_xs_shim_check ${scenario})
endforeach()
# 77: the desktop runtime accepts the heap-indexing flags (shader model 6.6), so the retry is unreachable.
set_tests_properties(d3d12_xs_shim_heap_indexing PROPERTIES SKIP_RETURN_CODE 77)
# D3D12XboxCreateDevice device-slot inventory and source-built creation fixture (#XCL-08).
set(d3d12x_pso_header "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_pso_cs.h")
add_custom_command(OUTPUT "${d3d12x_pso_header}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E CSMain -Vn d3d12x_pso_cs
            -Fh "${d3d12x_pso_header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_pso_cs.cso"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/d3d12x_pso.hlsl"
    DEPENDS tests/d3d12x_pso.hlsl
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_pso_cs.cso" VERBATIM)
# tests/d3d12x_device_check.cpp is compiled once for the check and its struct-return control (same flags,
# same include directories in the same order).
add_library(d3d12x_device_check_obj OBJECT tests/d3d12x_device_check.cpp "${d3d12x_pso_header}")
target_include_directories(d3d12x_device_check_obj PRIVATE "${CMAKE_CURRENT_BINARY_DIR}" src)
target_compile_features(d3d12x_device_check_obj PRIVATE cxx_std_17)
add_executable(d3d12x_device_check $<TARGET_OBJECTS:d3d12x_device_check_obj> src/d3d12x_struct_return.cpp "${d3d12x_pso_header}")
add_dependencies(d3d12x_device_check d3d12_xs_shim)
target_include_directories(d3d12x_device_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(d3d12x_device_check PRIVATE cxx_std_17)
target_include_directories(d3d12x_device_check PRIVATE src)
target_link_libraries(d3d12x_device_check PRIVATE d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME d3d12x_device_create_${adapter} COMMAND d3d12x_device_check
        "$<TARGET_FILE:d3d12_xs_shim>" create ${adapter})
    add_test(NAME d3d12x_device_negative_${adapter} COMMAND d3d12x_device_check
        "$<TARGET_FILE:d3d12_xs_shim>" negative ${adapter})
    add_test(NAME d3d12x_device_struct_return_${adapter} COMMAND d3d12x_device_check
        "$<TARGET_FILE:d3d12_xs_shim>" struct-return ${adapter})
endforeach()
set_tests_properties(d3d12x_device_create_hardware d3d12x_device_negative_hardware
    d3d12x_device_struct_return_hardware PROPERTIES
    SKIP_RETURN_CODE 77)
set_tests_properties(d3d12x_device_negative_warp d3d12x_device_negative_hardware PROPERTIES
    PASS_REGULAR_EXPRESSION "D3D12XboxCreateDevice: unsupported IID \\{7c0e1a10-5f2d-4b7a-9a51-3d9c6b2e8f01\\}")
# Negative control for the struct-return rejection cases: a build-tree copy of the adapter that
# writes through the second candidate when neither candidate is the device.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS src/d3d12x_struct_return.cpp)
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/src/d3d12x_struct_return.cpp" d3d12x_struct_return_text)
string(REGEX REPLACE "} else {(\r?\n +)return nullptr;" "} else {\\1output = second;"
    d3d12x_struct_return_control_text "${d3d12x_struct_return_text}")
if(d3d12x_struct_return_control_text STREQUAL d3d12x_struct_return_text)
    message(FATAL_ERROR "d3d12x_struct_return.cpp lost the anchor used by d3d12x_device_struct_return_neither_control")
endif()
set(d3d12x_struct_return_control "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_struct_return_control/d3d12x_struct_return.cpp")
file(WRITE "${d3d12x_struct_return_control}" "${d3d12x_struct_return_control_text}")
add_executable(d3d12x_device_struct_return_control $<TARGET_OBJECTS:d3d12x_device_check_obj>
    "${d3d12x_struct_return_control}" "${d3d12x_pso_header}")
add_dependencies(d3d12x_device_struct_return_control d3d12_xs_shim)
target_include_directories(d3d12x_device_struct_return_control PRIVATE "${CMAKE_CURRENT_BINARY_DIR}" src)
target_compile_features(d3d12x_device_struct_return_control PRIVATE cxx_std_17)
target_link_libraries(d3d12x_device_struct_return_control PRIVATE d3d12 dxgi)
add_test(NAME d3d12x_device_struct_return_neither_control_warp COMMAND d3d12x_device_struct_return_control
    "$<TARGET_FILE:d3d12_xs_shim>" struct-return warp)
set_tests_properties(d3d12x_device_struct_return_neither_control_warp PROPERTIES
    PASS_REGULAR_EXPRESSION "FAIL: struct_return reject neither_is_device: returned ")
# Static-sampler root signature and compute PSO through D3D12XboxCreateDevice (#XCL-19).
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME d3d12x_pso_static_sampler_${adapter} COMMAND d3d12x_device_check
        "$<TARGET_FILE:d3d12_xs_shim>" pso ${adapter})
endforeach()
add_test(NAME d3d12x_pso_reject_warp COMMAND d3d12x_device_check
    "$<TARGET_FILE:d3d12_xs_shim>" reject warp)
set_tests_properties(d3d12x_pso_static_sampler_hardware PROPERTIES SKIP_RETURN_CODE 77)

# D3D12.X descriptor heaps, CPU/GPU handles and descriptor table records (#XCL-09).
set(d3d12x_descriptor_cs "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_descriptor_cs.h")
add_custom_command(OUTPUT "${d3d12x_descriptor_cs}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E CSMain -Vn d3d12x_descriptor_cs
            -Fh "${d3d12x_descriptor_cs}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_descriptor_cs.cso"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/d3d12x_descriptor.hlsl"
    DEPENDS tests/d3d12x_descriptor.hlsl
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_descriptor_cs.cso" VERBATIM)
add_custom_target(d3d12x_descriptor_shader DEPENDS "${d3d12x_descriptor_cs}")
add_executable(d3d12x_descriptor_check tests/d3d12x_descriptor_check.cpp "${d3d12x_descriptor_cs}")
add_dependencies(d3d12x_descriptor_check d3d12_xs_shim d3d12x_descriptor_shader)
target_include_directories(d3d12x_descriptor_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(d3d12x_descriptor_check PRIVATE cxx_std_17)
target_link_libraries(d3d12x_descriptor_check PRIVATE d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME d3d12x_descriptor_heap_${adapter} COMMAND d3d12x_descriptor_check
        "$<TARGET_FILE:d3d12_xs_shim>" heap ${adapter})
    add_test(NAME d3d12x_descriptor_table_${adapter} COMMAND d3d12x_descriptor_check
        "$<TARGET_FILE:d3d12_xs_shim>" table ${adapter})
    add_test(NAME d3d12x_descriptor_negative_${adapter} COMMAND d3d12x_descriptor_check
        "$<TARGET_FILE:d3d12_xs_shim>" negative ${adapter})
    set_tests_properties(d3d12x_descriptor_heap_${adapter} d3d12x_descriptor_table_${adapter}
        d3d12x_descriptor_negative_${adapter} PROPERTIES TIMEOUT 30)
endforeach()
set_tests_properties(d3d12x_descriptor_heap_hardware d3d12x_descriptor_table_hardware
    d3d12x_descriptor_negative_hardware PROPERTIES SKIP_RETURN_CODE 77)
# D3D12.X compute command list recording, transitions, clear and readback (#XCL-10).
set(d3d12x_compute_list_cs "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_compute_list_cs.h")
add_custom_command(OUTPUT "${d3d12x_compute_list_cs}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E CSMain -Vn d3d12x_compute_list_cs
            -Fh "${d3d12x_compute_list_cs}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_compute_list_cs.cso"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/d3d12x_compute_list.hlsl"
    DEPENDS tests/d3d12x_compute_list.hlsl
    BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_compute_list_cs.cso" VERBATIM)
add_custom_target(d3d12x_compute_list_shader DEPENDS "${d3d12x_compute_list_cs}")
# tests/desktop_gpu.cpp again, with the include directory these two checks use.
add_library(d3d12x_desktop_gpu_obj OBJECT tests/desktop_gpu.cpp)
target_include_directories(d3d12x_desktop_gpu_obj PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(d3d12x_desktop_gpu_obj PRIVATE cxx_std_17)
add_executable(d3d12x_compute_list_check tests/d3d12x_compute_list_check.cpp
    $<TARGET_OBJECTS:d3d12x_desktop_gpu_obj> "${d3d12x_compute_list_cs}")
add_dependencies(d3d12x_compute_list_check d3d12_xs_shim d3d12x_compute_list_shader)
target_include_directories(d3d12x_compute_list_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(d3d12x_compute_list_check PRIVATE cxx_std_17)
target_link_libraries(d3d12x_compute_list_check PRIVATE d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME d3d12x_compute_list_${adapter} COMMAND d3d12x_compute_list_check
        "$<TARGET_FILE:d3d12_xs_shim>" ${adapter})
    set_tests_properties(d3d12x_compute_list_${adapter} PROPERTIES TIMEOUT 30)
endforeach()
set_tests_properties(d3d12x_compute_list_hardware PROPERTIES SKIP_RETURN_CODE 77)

# D3D12.X graphics command list: one source-built triangle through a VS/PS PSO (#XCL-12).
foreach(stage IN ITEMS vs ps)
    string(TOUPPER "${stage}" entry)
    set(d3d12x_graphics_header "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_graphics_${stage}.h")
    add_custom_command(OUTPUT "${d3d12x_graphics_header}"
        COMMAND "${DXC_EXECUTABLE}" -T ${stage}_6_0 -E ${entry}Main -Vn d3d12x_graphics_${stage}
                -Fh "${d3d12x_graphics_header}" -Fo "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_graphics_${stage}.cso"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/d3d12x_graphics.hlsl"
        DEPENDS tests/d3d12x_graphics.hlsl
        BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/d3d12x_graphics_${stage}.cso" VERBATIM)
    set(d3d12x_graphics_${stage} "${d3d12x_graphics_header}")
endforeach()
add_custom_target(d3d12x_graphics_shader DEPENDS
    "${d3d12x_graphics_vs}"
    "${d3d12x_graphics_ps}")
add_executable(d3d12x_graphics_list_check tests/d3d12x_graphics_list_check.cpp $<TARGET_OBJECTS:d3d12x_desktop_gpu_obj>
    "${d3d12x_graphics_vs}" "${d3d12x_graphics_ps}")
add_dependencies(d3d12x_graphics_list_check d3d12_xs_shim d3d12x_graphics_shader)
target_include_directories(d3d12x_graphics_list_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(d3d12x_graphics_list_check PRIVATE cxx_std_17)
target_link_libraries(d3d12x_graphics_list_check PRIVATE d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME d3d12x_graphics_list_${adapter} COMMAND d3d12x_graphics_list_check
        "$<TARGET_FILE:d3d12_xs_shim>" ${adapter})
    set_tests_properties(d3d12x_graphics_list_${adapter} PROPERTIES TIMEOUT 60)
endforeach()
set_tests_properties(d3d12x_graphics_list_hardware PROPERTIES SKIP_RETURN_CODE 77)
# The main executable's CPU/GPU range translation against a desktop D3D12 heap (#874).
set(vm_translation_header "${CMAKE_CURRENT_BINARY_DIR}/vm_translation_cs.h")
add_custom_command(OUTPUT "${vm_translation_header}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main -Vn vm_translation_cs -Fh "${vm_translation_header}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/vm_translation.hlsl"
    DEPENDS tests/vm_translation.hlsl VERBATIM)
add_executable(vm_translation_check tests/vm_translation_check.cpp src/d3d12_xs_range.cpp "${vm_translation_header}")
target_include_directories(vm_translation_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}" tests src)
target_compile_features(vm_translation_check PRIVATE cxx_std_17)
target_link_libraries(vm_translation_check PRIVATE d3d12_xs_shim d3d12 dxgi)
add_test(NAME vm_translation_shared_range COMMAND vm_translation_check shared_range)
foreach(adapter IN ITEMS warp hardware)
    foreach(scenario IN ITEMS device sequence range range_lifetime range_partial)
        add_test(NAME vm_translation_${scenario}_${adapter} COMMAND vm_translation_check ${scenario}_${adapter})
        set_tests_properties(vm_translation_${scenario}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    endforeach()
endforeach()
# One linear CPU-written, GPU-read buffer of title-style memory through real sharing, forced copying
# and forced sharing failure (#1914). Test-only. Each mutated run removes one guarantee (submit-time
# refresh, copy-back after the fence, fence-gated reuse) and must fail every case it protects.
add_executable(unified_buffer_paths_check tests/unified_buffer_paths_check.cpp "${vm_translation_header}")
target_include_directories(unified_buffer_paths_check PRIVATE "${CMAKE_CURRENT_BINARY_DIR}" tests)
target_compile_features(unified_buffer_paths_check PRIVATE cxx_std_17)
target_link_libraries(unified_buffer_paths_check PRIVATE d3d12 dxgi OneCore)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME unified_buffer_paths_${adapter} COMMAND unified_buffer_paths_check ${adapter})
    set_tests_properties(unified_buffer_paths_${adapter} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
endforeach()
foreach(mutant IN ITEMS skip_refresh skip_copy_back reuse_early)
    string(REPLACE "_" "-" flag "${mutant}")
    add_test(NAME unified_buffer_paths_${mutant}_control COMMAND unified_buffer_paths_check --mutate ${flag} warp)
    set_tests_properties(unified_buffer_paths_${mutant}_control PROPERTIES WILL_FAIL TRUE TIMEOUT 90
        SKIP_RETURN_CODE 77)
endforeach()
# The production slice (#1914): slot 133's opt-in linear-buffer backing (X2W_D3D12_LINEAR_BUFFERS,
# src/startup_stubs/linear_buffer_backing.h) through the device and queue wrappers of d3d12_xs.dll, over
# XMem pages and a private range: the default, real sharing, forced copying, host sharing refusal, a
# copy without a submit fence (the default backing is kept and the refusal reported), a refresh that
# cannot be staged (the submission runs, the buffer is reported stale) and a one-buffer staging pool
# (a waiting refresh must not block release(), the info export or another queue). Refreshes run on an
# internal copy queue; the copy path also reads on COMPUTE and COPY queues, reads one buffer on two
# queues after one CPU write (both must see it), and follows a title-owned cross-queue fence without
# deadlock. It also counts the backings in the D3D12 budget, keeps a buffer a submitted list copy wrote
# (and refreshes one whose copy was discarded), orders a refresh behind an earlier read on another queue,
# refuses a submission whose refresh would have to wait for a queue behind an unreached title Wait (also
# when that Wait and the submission behind it arrive on two threads), publishes two threads' refreshes in execution order, skips a buffer released and freed mid-refresh, and
# defers XMem placements to the mesh XMem lease path when that is on. Each mutant removes one guarantee in
# the DLL and must fail its case.
add_executable(linear_buffer_backing_check tests/linear_buffer_backing_check.cpp)
target_include_directories(linear_buffer_backing_check PRIVATE tests)
target_compile_features(linear_buffer_backing_check PRIVATE cxx_std_17)
target_link_libraries(linear_buffer_backing_check PRIVATE xmem_shim d3d12_xs_shim d3d12 dxgi d3dcompiler)
foreach(adapter IN ITEMS warp hardware)
    foreach(path IN ITEMS default share copy refusal untracked stale contention lease)
        add_test(NAME linear_buffer_backing_${path}_${adapter} COMMAND linear_buffer_backing_check ${adapter} ${path})
        set_tests_properties(linear_buffer_backing_${path}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
endforeach()
foreach(control IN ITEMS copy:skip_refresh copy:reuse_early copy:copy_gpu_writes refusal:ignore_feature
        copy:refusal_silent contention:hold_lock copy:skip_consumer_wait copy:refresh_gpu_written copy:gpuw_at_record
        copy:skip_producer_wait copy:publish_out_of_order copy:copy_after_retire copy:accept_unsafe_refresh
        copy:unlocked_title_wait)
    string(REPLACE ":" ";" parts "${control}")
    list(GET parts 0 path)
    list(GET parts 1 mutant)
    string(REPLACE "_" "-" flag "${mutant}")
    add_test(NAME linear_buffer_backing_${mutant}_control COMMAND linear_buffer_backing_check warp ${path} --mutate ${flag})
    set_tests_properties(linear_buffer_backing_${mutant}_control PROPERTIES WILL_FAIL TRUE TIMEOUT 120
        SKIP_RETURN_CODE 77)
endforeach()
# The configured range's windows and GPU addresses (src/d3d12_xs_range.h) with a fake device and fake
# windows. The mutated run is the negative control.
add_executable(d3d12_xs_range_check tests/d3d12_xs_range_check.cpp src/d3d12_xs_range.cpp)
target_include_directories(d3d12_xs_range_check PRIVATE src)
target_compile_features(d3d12_xs_range_check PRIVATE cxx_std_17)
add_test(NAME d3d12_xs_range COMMAND d3d12_xs_range_check)
add_test(NAME d3d12_xs_range_full_last_window_control COMMAND d3d12_xs_range_check --mutate full_last_window)
set_tests_properties(d3d12_xs_range_full_last_window_control PROPERTIES WILL_FAIL TRUE)
# XG-style swizzle selection compared with AMD addrlib (#870). addrlib is an optional local dependency
# fetched by tools/fetch_addrlib.py into out/deps/mesa (Mesa 25.1.0, src/amd/addrlib, MIT); without it the
# test skips (77). The source list and definitions follow Mesa's src/amd/addrlib/meson.build.
set(_addrlib_default "${CMAKE_CURRENT_SOURCE_DIR}/out/deps/mesa/src/amd/addrlib")
if(NOT EXISTS "${_addrlib_default}/inc/addrinterface.h")
    set(_addrlib_default "")
endif()
set(XBOX2WINDOWS_ADDRLIB_DIR "${_addrlib_default}" CACHE PATH
    "AMD addrlib source (Mesa src/amd/addrlib, see tools/fetch_addrlib.py); empty skips xg_swizzle_select")
add_executable(xg_swizzle_select_check tests/xg_swizzle_select_check.cpp)
target_compile_features(xg_swizzle_select_check PRIVATE cxx_std_17)
if(XBOX2WINDOWS_ADDRLIB_DIR)
    if(NOT EXISTS "${XBOX2WINDOWS_ADDRLIB_DIR}/inc/addrinterface.h")
        message(FATAL_ERROR "XBOX2WINDOWS_ADDRLIB_DIR=${XBOX2WINDOWS_ADDRLIB_DIR} has no inc/addrinterface.h")
    endif()
    set(_a "${XBOX2WINDOWS_ADDRLIB_DIR}")
    add_library(xbw_addrlib STATIC EXCLUDE_FROM_ALL
        "${_a}/src/addrinterface.cpp" "${_a}/src/core/addrelemlib.cpp" "${_a}/src/core/addrlib.cpp"
        "${_a}/src/core/addrlib1.cpp" "${_a}/src/core/addrlib2.cpp" "${_a}/src/core/addrlib3.cpp"
        "${_a}/src/core/addrobject.cpp" "${_a}/src/core/addrswizzler.cpp" "${_a}/src/core/coord.cpp"
        "${_a}/src/gfx9/gfx9addrlib.cpp" "${_a}/src/gfx10/gfx10addrlib.cpp" "${_a}/src/gfx11/gfx11addrlib.cpp"
        "${_a}/src/gfx12/gfx12addrlib.cpp" "${_a}/src/r800/ciaddrlib.cpp" "${_a}/src/r800/egbaddrlib.cpp"
        "${_a}/src/r800/siaddrlib.cpp")
    target_include_directories(xbw_addrlib PUBLIC "${_a}/inc" PRIVATE "${_a}/src" "${_a}/src/core"
        "${_a}/src/chip/gfx9" "${_a}/src/chip/r800" "${_a}/src/chip/gfx10" "${_a}/src/chip/gfx11" "${_a}/src/chip/gfx12")
    target_compile_definitions(xbw_addrlib PUBLIC ADDR_FASTCALL= PRIVATE LITTLEENDIAN_CPU DEBUG=0)
    target_compile_options(xbw_addrlib PRIVATE /w)
    target_link_libraries(xg_swizzle_select_check PRIVATE xbw_addrlib)
    target_compile_definitions(xg_swizzle_select_check PRIVATE XBOX2WINDOWS_HAVE_ADDRLIB)
    message(STATUS "xg_swizzle_select: addrlib from ${XBOX2WINDOWS_ADDRLIB_DIR}")
else()
    message(STATUS "xg_swizzle_select: addrlib not configured, the test will skip (77)")
endif()
add_test(NAME xg_bc64_tiling_reference COMMAND xg_swizzle_select_check --bc64-tiling)
set_tests_properties(xg_bc64_tiling_reference PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
if(EXISTS "${INTAKE_PYTHON}")
    add_test(NAME tooling_fetch_addrlib_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/fetch_addrlib_cli_check.py")
    set_tests_properties(tooling_fetch_addrlib_cli_check PROPERTIES TIMEOUT 60)
endif()
# 4 KiB allocation answers for small 2D textures (src/startup_stubs/small_texture_4k.h): literal sizes and
# refused descriptions without a device; the mutated run is the negative control; the addrlib run compares
# every accepted shape with addrlib's GFX10 4 KiB layout and skips (77) without addrlib.
add_executable(startup_small_texture_4k_check tests/startup_small_texture_4k_check.cpp)
target_compile_features(startup_small_texture_4k_check PRIVATE cxx_std_17)
target_include_directories(startup_small_texture_4k_check PRIVATE src)
if(XBOX2WINDOWS_ADDRLIB_DIR)
    target_link_libraries(startup_small_texture_4k_check PRIVATE xbw_addrlib)
    target_compile_definitions(startup_small_texture_4k_check PRIVATE XBOX2WINDOWS_HAVE_ADDRLIB)
endif()
add_test(NAME startup_small_texture_4k COMMAND startup_small_texture_4k_check)
add_test(NAME startup_small_texture_4k_whole_width_tail_control COMMAND startup_small_texture_4k_check --mutate whole-width-tail)
set_tests_properties(startup_small_texture_4k_whole_width_tail_control PROPERTIES WILL_FAIL TRUE)
add_test(NAME startup_small_texture_4k_addrlib COMMAND startup_small_texture_4k_check --addrlib)
set_tests_properties(startup_small_texture_4k_addrlib PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
# The same answers through the device wrapper: allocation-info slots 25 and 108, with controls.
add_executable(startup_small_texture_4k_device_check tests/startup_small_texture_4k_device_check.cpp)
target_compile_features(startup_small_texture_4k_device_check PRIVATE cxx_std_17)
target_link_libraries(startup_small_texture_4k_device_check PRIVATE d3d12_xs_shim d3d12 dxgi)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME startup_small_texture_4k_device_${adapter} COMMAND startup_small_texture_4k_device_check ${adapter})
endforeach()
set_tests_properties(startup_small_texture_4k_device_hardware PROPERTIES SKIP_RETURN_CODE 77)
# Which descriptions take the 64 KiB standard BC chain (src/startup_stubs/bc64_chain.h), without addrlib
# or a device. The mutated run expects layout UNKNOWN to be accepted and is the negative control.
add_executable(startup_bc64_supports_check tests/startup_bc64_supports_check.cpp)
target_compile_features(startup_bc64_supports_check PRIVATE cxx_std_17)
target_include_directories(startup_bc64_supports_check PRIVATE src)
add_test(NAME startup_bc64_supports COMMAND startup_bc64_supports_check)
add_test(NAME startup_bc64_supports_layout_control COMMAND startup_bc64_supports_check --mutate layout)
set_tests_properties(startup_bc64_supports_layout_control PROPERTIES WILL_FAIL TRUE)
# Which descriptions take the single-element memory SRV path (src/startup_stubs/single_element_srv.h), without
# a device. The mutated run expects an XOR layout to be accepted and is the negative control.
add_executable(startup_single_element_srv_check tests/startup_single_element_srv_check.cpp)
target_compile_features(startup_single_element_srv_check PRIVATE cxx_std_17)
target_include_directories(startup_single_element_srv_check PRIVATE src)
add_test(NAME startup_single_element_srv COMMAND startup_single_element_srv_check)
add_test(NAME startup_single_element_srv_xor_control COMMAND startup_single_element_srv_check --mutate xor)
set_tests_properties(startup_single_element_srv_xor_control PROPERTIES WILL_FAIL TRUE)
# Slot-10 tile plan for layout 0x10a (src/startup_stubs/tile64_plan.h) without a device: tile shapes,
# accepted descriptions and hand-worked plans. The mutated runs are negative controls.
add_executable(startup_tile64_plan_check tests/startup_tile64_plan_check.cpp)
target_compile_features(startup_tile64_plan_check PRIVATE cxx_std_17)
target_include_directories(startup_tile64_plan_check PRIVATE src)
add_test(NAME startup_tile64_plan COMMAND startup_tile64_plan_check)
foreach(mutation IN ITEMS bc4 width clamp)
    add_test(NAME startup_tile64_plan_${mutation}_control COMMAND startup_tile64_plan_check --mutate ${mutation})
    set_tests_properties(startup_tile64_plan_${mutation}_control PROPERTIES WILL_FAIL TRUE)
endforeach()
# Console texture layouts for the non-XOR standard and display swizzle modes (src/startup_stubs/gfx10_layout.h)
# and the slot-70 descriptions that use them (src/startup_stubs/address_texture.h), without a device: address
# equations against the pattern rows of AMD addrlib (Mesa 25.1.0, src/amd/addrlib, MIT), agreement with
# bc7_4k_s.h, bc64_chain.h and tile64_plan.h, and round trips. The mutated run reads the display order as the standard one and is a negative control.
add_executable(startup_gfx10_layout_check tests/startup_gfx10_layout_check.cpp)
target_compile_features(startup_gfx10_layout_check PRIVATE cxx_std_17)
target_include_directories(startup_gfx10_layout_check PRIVATE src)
add_test(NAME startup_gfx10_layout COMMAND startup_gfx10_layout_check)
add_test(NAME startup_gfx10_layout_display_control COMMAND startup_gfx10_layout_check --mutate display)
set_tests_properties(startup_gfx10_layout_display_control PROPERTIES WILL_FAIL TRUE)
add_test(NAME xg_swizzle_select COMMAND xg_swizzle_select_check)
set_tests_properties(xg_swizzle_select PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
# Mutation control: the same comparison must identify all nine mismatches.
add_test(NAME xg_swizzle_select_mutation COMMAND xg_swizzle_select_check --mutate-linear-fallback)
set_tests_properties(xg_swizzle_select_mutation PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
add_test(NAME xg_swizzle_factory COMMAND xg_swizzle_select_check --factory)
add_test(NAME xg_swizzle_factory_no_write COMMAND xg_swizzle_select_check --mutate-factory-no-write)
set_tests_properties(xg_swizzle_factory xg_swizzle_factory_no_write PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
foreach(adapter IN ITEMS hardware warp)
    add_test(NAME offscreen_${adapter} COMMAND offscreen_check ${adapter} triangle_${adapter}.bmp)
    add_test(NAME ffx_provider_loop_${adapter} COMMAND offscreen_check ${adapter} --ffx-provider-loop)
    add_test(NAME ffx_device_init_${adapter} COMMAND offscreen_check ${adapter} --ffx-device-init)
    add_test(NAME ffx_recurrent_${adapter} COMMAND offscreen_check ${adapter} --ffx-recurrent)
    add_test(NAME dual_uav_${adapter} COMMAND offscreen_check ${adapter} --dual-uav)
    add_test(NAME stream_root_srv_${adapter} COMMAND offscreen_check ${adapter} --stream-root-srv)
    set_tests_properties(stream_root_srv_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME descriptor_window_submissions_${adapter} COMMAND offscreen_check ${adapter} --descriptor-window-submissions)
    foreach(mode IN ITEMS refresh stale)
        add_test(NAME cpu_srv_${mode}_${adapter} COMMAND offscreen_check ${adapter} --cpu-srv-${mode})
        set_tests_properties(cpu_srv_${mode}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME descriptor_window_stale_${adapter} COMMAND offscreen_check ${adapter} --descriptor-window-stale)
    set_tests_properties(descriptor_window_submissions_${adapter} descriptor_window_stale_${adapter}
        PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(descriptor_window_stale_${adapter}
        PROPERTIES FAIL_REGULAR_EXPRESSION "descriptor_windows submit=2 slot=[1-9]")
    foreach(scenario IN ITEMS live stale unknown)
        add_test(NAME descriptor_record_copy_${scenario}_${adapter}
            COMMAND offscreen_check ${adapter} --descriptor-record-copy ${scenario})
        set_tests_properties(descriptor_record_copy_${scenario}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME texture_mips_${adapter} COMMAND offscreen_check ${adapter} --texture-mips)
    add_test(NAME dynamic_sampler_index_${adapter} COMMAND offscreen_check ${adapter} --dynamic-sampler-index)
    set_tests_properties(dynamic_sampler_index_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(dual_uav_${adapter} texture_mips_${adapter} PROPERTIES TIMEOUT 45)
    add_test(NAME dxr_query_${adapter} COMMAND offscreen_check ${adapter} --ray-query)
    add_test(NAME dxr_address_ranges_${adapter} COMMAND offscreen_check ${adapter} --dxr-address-ranges)
    add_test(NAME dxr_placed_build_${adapter} COMMAND offscreen_check ${adapter} --dxr-placed-build)
    set_tests_properties(dxr_placed_build_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME dxr_slot70_as_${adapter} COMMAND offscreen_check ${adapter} --dxr-slot70-as)
    set_tests_properties(dxr_slot70_as_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(dxr_address_ranges_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME dxr_pipeline_${adapter} COMMAND offscreen_check ${adapter} --dxr-pipeline)
    add_test(NAME dxr_update_${adapter} COMMAND offscreen_check ${adapter} --dxr-update)
    add_test(NAME dxr_update_pipeline_${adapter} COMMAND offscreen_check ${adapter} --dxr-update-pipeline)
    set_tests_properties(dxr_update_${adapter} dxr_update_pipeline_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME dxr_facing_${adapter} COMMAND offscreen_check ${adapter} --dxr-facing)
    add_test(NAME dxr_facing_pipeline_${adapter} COMMAND offscreen_check ${adapter} --dxr-facing-pipeline)
    set_tests_properties(dxr_facing_${adapter} dxr_facing_pipeline_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME dxr_opacity_${adapter} COMMAND offscreen_check ${adapter} --dxr-opacity)
    add_test(NAME dxr_opacity_pipeline_${adapter} COMMAND offscreen_check ${adapter} --dxr-opacity-pipeline)
    set_tests_properties(dxr_opacity_${adapter} dxr_opacity_pipeline_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME bvh_buffer_ops_${adapter} COMMAND offscreen_check ${adapter} --buffer-ops)
    add_test(NAME gpu_alias_${adapter} COMMAND offscreen_check ${adapter} --gpu-alias)
    add_test(NAME gpu_alias_window_${adapter} COMMAND offscreen_check ${adapter} --gpu-alias-window)
    add_test(NAME gpu_alias_lookup_${adapter} COMMAND offscreen_check ${adapter} --gpu-alias-lookup)
    add_test(NAME gpu_alias_lookup_writes_${adapter} COMMAND offscreen_check ${adapter} --gpu-alias-lookup-writes)
    add_test(NAME gpu_alias_registry_${adapter} COMMAND offscreen_check ${adapter} --gpu-alias-registry)
    set_tests_properties(gpu_alias_${adapter} gpu_alias_window_${adapter} gpu_alias_lookup_${adapter}
        gpu_alias_lookup_writes_${adapter} gpu_alias_registry_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME bvh_root_roundtrip_${adapter} COMMAND offscreen_check ${adapter} --bvh-root-roundtrip)
    set_tests_properties(bvh_root_roundtrip_${adapter} PROPERTIES TIMEOUT 45)
    foreach(work IN ITEMS reads waves wave64 hits differential atomics numeric packed)
        add_test(NAME bvh_${work}_${adapter} COMMAND offscreen_check ${adapter} --bvh-${work})
        set_tests_properties(bvh_${work}_${adapter} PROPERTIES TIMEOUT 45)
    endforeach()
    set_tests_properties(bvh_wave64_${adapter} bvh_differential_${adapter} PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME wave_shuffle_${adapter} COMMAND offscreen_check ${adapter} --wave-shuffle)
    set_tests_properties(wave_shuffle_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    add_test(NAME wave64_emulate_${adapter} COMMAND offscreen_check ${adapter} --wave64-emulate)
    set_tests_properties(wave64_emulate_${adapter} PROPERTIES TIMEOUT 45)
    add_test(NAME shader_wave_${adapter} COMMAND offscreen_check ${adapter} --shader-wave)
    set_tests_properties(shader_wave_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    foreach(width IN ITEMS 32 64)
        add_test(NAME shader_wave${width}_${adapter} COMMAND offscreen_check ${adapter} --shader-wave${width})
        set_tests_properties(shader_wave${width}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    endforeach()
    set_tests_properties(bvh_buffer_ops_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(dxr_query_${adapter} dxr_pipeline_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(offscreen_${adapter} PROPERTIES TIMEOUT 45)
endforeach()
set_tests_properties(wave64_emulate_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(offscreen_hardware ffx_device_init_hardware ffx_recurrent_hardware ffx_provider_loop_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(dual_uav_hardware texture_mips_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(bvh_root_roundtrip_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(bvh_atomics_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(bvh_numeric_hardware bvh_packed_hardware PROPERTIES SKIP_RETURN_CODE 77)
set_tests_properties(bvh_reads_hardware bvh_waves_hardware bvh_hits_hardware PROPERTIES SKIP_RETURN_CODE 77)
# The cs_6_5 fixtures skip on a WARP below SM 6.5. The Windows 10 in-box WARP reports SM 6.2.
set_tests_properties(bvh_reads_warp bvh_waves_warp bvh_hits_warp bvh_packed_warp
    bvh_numeric_warp bvh_atomics_warp PROPERTIES SKIP_RETURN_CODE 77)
# CRT-free startup attempt for a forced-wave compute pipeline (Refs #870; the desktop readback is #1132).
# One EXE per shader variant and adapter, so the entry point takes no arguments. Each prints the
# D3D12_OPTIONS1 lane range, the exact CreateComputePipelineState HRESULT and the debug-layer messages,
# and reads back WaveGetLaneCount() when creation succeeds. An adapter whose range excludes the forced
# width must refuse the pipeline and exits 77 with the HRESULT; creation that contradicts the range fails.
foreach(width IN ITEMS 0 4 32)
    set(variant_dir "${CMAKE_CURRENT_BINARY_DIR}/wave_startup_${width}")
    set(defines)
    if(width)
        set(defines -D WAVE_STARTUP_WIDTH=${width})
    endif()
    add_custom_command(OUTPUT "${variant_dir}/wave_startup_cs.h"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${variant_dir}"
        COMMAND "${DXC_EXECUTABLE}" -T cs_6_6 -E main ${defines} -Vn wave_startup_cs
                -Fh "${variant_dir}/wave_startup_cs.h" "${CMAKE_CURRENT_SOURCE_DIR}/tests/wave_startup.hlsl"
        DEPENDS tests/wave_startup.hlsl VERBATIM)
    foreach(adapter IN ITEMS warp hardware)
        set(target wave_startup_${width}_${adapter})
        add_executable(${target} tests/wave_startup_exe.cpp "${variant_dir}/wave_startup_cs.h")
        target_include_directories(${target} PRIVATE "${variant_dir}")
        string(COMPARE EQUAL "${adapter}" warp is_warp)
        target_compile_definitions(${target} PRIVATE WAVE_STARTUP_WIDTH=${width} WAVE_STARTUP_WARP=$<BOOL:${is_warp}>)
        target_compile_options(${target} PRIVATE /GS- /Zl)
        target_link_options(${target} PRIVATE /ENTRY:fixture_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE
            /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(${target} PRIVATE kernel32 d3d12 dxgi)
        add_test(NAME ${target} COMMAND ${target})
        set_tests_properties(${target} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    endforeach()
endforeach()

add_test(NAME bvh_differential_pipeline_warp COMMAND offscreen_check warp --bvh-differential-pipeline)
set_tests_properties(bvh_differential_pipeline_warp PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)

add_test(NAME offscreen_invalid_operation_warp COMMAND "${CMAKE_COMMAND}"
    "-DRENDERER=$<TARGET_FILE:offscreen_check>" -P "${CMAKE_SOURCE_DIR}/tests/offscreen_invalid_operation.cmake")
set_tests_properties(offscreen_invalid_operation_warp PROPERTIES TIMEOUT 45)

add_test(NAME offscreen_capability_table_self_test COMMAND offscreen_check --self-test)
set_tests_properties(offscreen_capability_table_self_test PROPERTIES TIMEOUT 45)
foreach(adapter IN ITEMS hardware warp)
    add_test(NAME mesh_shader_pipeline_${adapter} COMMAND offscreen_check ${adapter} --mesh-shader-pipeline)
    add_test(NAME mesh_shader_pipeline_fallback_${adapter}
        COMMAND offscreen_check ${adapter} --mesh-shader-pipeline-fallback)
    set_tests_properties(mesh_shader_pipeline_${adapter} mesh_shader_pipeline_fallback_${adapter}
        PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
endforeach()
foreach(adapter IN ITEMS hardware warp)
    add_test(NAME descriptor_heap_paging_${adapter} COMMAND offscreen_check ${adapter} --descriptor-heap-paging)
    add_test(NAME descriptor_heap_paging_swapped_${adapter}
        COMMAND offscreen_check ${adapter} --descriptor-heap-paging-swapped)
    set_tests_properties(descriptor_heap_paging_${adapter} descriptor_heap_paging_swapped_${adapter}
        PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(descriptor_heap_paging_swapped_${adapter}
        PROPERTIES FAIL_REGULAR_EXPRESSION "descriptor_paging swapped=0")
endforeach()
foreach(adapter IN ITEMS hardware warp)
    add_test(NAME startup_sampler_x_${adapter} COMMAND offscreen_check ${adapter} --startup-sampler-x)
    add_test(NAME startup_sampler_x_swapped_${adapter} COMMAND offscreen_check ${adapter} --startup-sampler-x-swapped)
    set_tests_properties(startup_sampler_x_${adapter} startup_sampler_x_swapped_${adapter}
        PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_sampler_x_swapped_${adapter}
        PROPERTIES FAIL_REGULAR_EXPRESSION "startup_sampler_x swapped=0")
    # The dropped control resets the decoded LOD limits and must read the wrong mip for both entries.
    add_test(NAME startup_sampler_lod_${adapter} COMMAND offscreen_check ${adapter} --startup-sampler-lod)
    add_test(NAME startup_sampler_lod_dropped_${adapter} COMMAND offscreen_check ${adapter} --startup-sampler-lod-dropped)
    set_tests_properties(startup_sampler_lod_${adapter} startup_sampler_lod_dropped_${adapter}
        PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77)
    set_tests_properties(startup_sampler_lod_dropped_${adapter}
        PROPERTIES PASS_REGULAR_EXPRESSION "startup_sampler_lod dropped_clamp wrong_mip=2 unexpected=0")
    add_test(NAME startup_cb_blend_${adapter} COMMAND offscreen_check ${adapter} --startup-cb-blend)
    add_test(NAME startup_cb_blend_swapped_${adapter} COMMAND offscreen_check ${adapter} --startup-cb-blend-swapped)
    set_tests_properties(startup_cb_blend_${adapter} startup_cb_blend_swapped_${adapter}
        PROPERTIES TIMEOUT 60)
    # Export write masks (#1674): the channels outside a manifest 'wmask' keep the target's value.
    add_test(NAME startup_export_write_mask_${adapter} COMMAND offscreen_check ${adapter} --startup-export-write-mask)
    add_test(NAME startup_export_write_mask_unmasked_${adapter} COMMAND offscreen_check ${adapter} --startup-export-write-mask-unmasked)
    set_tests_properties(startup_export_write_mask_${adapter} startup_export_write_mask_unmasked_${adapter}
        PROPERTIES TIMEOUT 60)
    add_test(NAME startup_composite_provenance_${adapter} COMMAND offscreen_check ${adapter} --startup-composite-provenance)
    set_tests_properties(startup_composite_provenance_${adapter} PROPERTIES TIMEOUT 60)
    add_test(NAME startup_range_provenance_${adapter} COMMAND offscreen_check ${adapter} --startup-range-provenance)
    set_tests_properties(startup_range_provenance_${adapter} PROPERTIES TIMEOUT 60)
endforeach()
set_tests_properties(startup_cb_blend_hardware startup_cb_blend_swapped_hardware
    startup_composite_provenance_hardware startup_range_provenance_hardware PROPERTIES SKIP_RETURN_CODE 77)

set(SIMPLE_TRIANGLE_DIR "${CMAKE_SOURCE_DIR}/out/reference/b1e77b6ac10f95b07296025fda171ca2ddc42dbe/Samples/IntroGraphics/SimpleTriangle"
    CACHE PATH "Microsoft SimpleTriangle sample directory")
if(EXISTS "${SIMPLE_TRIANGLE_DIR}/VertexShader.hlsl")
    find_program(REFERENCE_POWERSHELL NAMES pwsh powershell REQUIRED)
    foreach(adapter IN ITEMS hardware warp)
        add_test(NAME reference_triangle_${adapter} COMMAND "${REFERENCE_POWERSHELL}" -NoProfile -ExecutionPolicy Bypass
            -File "${CMAKE_SOURCE_DIR}/tests/reference_triangle.ps1" -Sample "${SIMPLE_TRIANGLE_DIR}"
            -Compiler "${DXC_EXECUTABLE}" -Renderer "$<TARGET_FILE:offscreen_check>" -Adapter ${adapter})
        set_tests_properties(reference_triangle_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    endforeach()
endif()

target_sources(offscreen_check PRIVATE tests/ffx_device_init.cpp tests/ffx_backend_slots.cpp tests/ffx_recurrent.cpp tests/ffx_provider_loop.cpp)
set(FFX_UPSCALER_IMAGE "" CACHE FILEPATH "Local Xbox upscaler DLL for offline backend translation")
set(FFX_DISPATCH_SHADER_DIR "" CACHE PATH "Directory containing locally translated FSR4 shaders and scratch_reference.h")
if(FFX_DISPATCH_SHADER_DIR)
    if(NOT FFX_UPSCALER_IMAGE)
        message(FATAL_ERROR "Package dispatch replay requires FFX_UPSCALER_IMAGE")
    endif()
    target_compile_definitions(offscreen_check PRIVATE FFX_DISPATCH_AOT)
    target_include_directories(offscreen_check PRIVATE "${FFX_DISPATCH_SHADER_DIR}")
endif()
target_sources(offscreen_check PRIVATE tests/ffx_dispatch.cpp tests/ffx_dispatch_scratch.cpp)
foreach(stage IN ITEMS pass24 pass25 producer rcas)
    set(shader "${CMAKE_CURRENT_SOURCE_DIR}/tests/ffx_dispatch_control.hlsl")
    set(entry "${stage}")
    if(FFX_DISPATCH_SHADER_DIR)
        set(shader "${FFX_DISPATCH_SHADER_DIR}/${stage}.hlsl")
        set(entry main)
    endif()
    set(storage_formats Native Packed)
    if(stage MATCHES "^pass")
        set(storage_formats Raw)
    endif()
    foreach(storage IN LISTS storage_formats)
        set(symbol "${stage}${storage}")
        set(header "${CMAKE_CURRENT_BINARY_DIR}/${symbol}.h")
        add_custom_command(OUTPUT "${header}"
            COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E "${entry}" -D "STORAGE_${storage}=1"
                -I "${CMAKE_CURRENT_SOURCE_DIR}/tests" -Vn "${symbol}" -Fh "${header}"
                -Fo "${CMAKE_CURRENT_BINARY_DIR}/${symbol}.cso" "${shader}"
            DEPENDS "${shader}" tests/ffx_dispatch_io.hlsli src/rgb9e5.hlsli src/ffx_float_to_int.hlsli
            BYPRODUCTS "${CMAKE_CURRENT_BINARY_DIR}/${symbol}.cso" VERBATIM)
        target_sources(offscreen_check PRIVATE "${header}")
    endforeach()
endforeach()
if(FFX_UPSCALER_IMAGE)
    if(NOT EXISTS "${INTAKE_PYTHON}" OR NOT EXISTS "${FFX_UPSCALER_IMAGE}")
        message(FATAL_ERROR "Package translation requires INTAKE_PYTHON and FFX_UPSCALER_IMAGE")
    endif()
    set(device_slice "${CMAKE_CURRENT_BINARY_DIR}/ffx_device_slice.cpp")
    add_custom_command(OUTPUT "${device_slice}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/ffx_device_init.py" "${FFX_UPSCALER_IMAGE}" "${device_slice}"
        DEPENDS "${FFX_UPSCALER_IMAGE}" tools/ffx_device_init.py tools/ffx_recurrent.py tools/ffx_provider_loop.py tools/ffx_dispatch_profile.py tools/ffx_version_query.py tools/cpu_ranges.py tools/cpu_leaf_aot.py
        VERBATIM)
    target_sources(offscreen_check PRIVATE "${device_slice}")
    target_include_directories(offscreen_check PRIVATE "${CMAKE_SOURCE_DIR}/tests")
    target_compile_definitions(offscreen_check PRIVATE FFX_PACKAGE_DEVICE_SLICE)
    get_filename_component(ffx_dir "${FFX_UPSCALER_IMAGE}" DIRECTORY)
    set(ffx_loader "${ffx_dir}/amd_fidelityfx_loader_xbox.dll")
    if(EXISTS "${ffx_loader}")
        set(loop_loader "${CMAKE_CURRENT_BINARY_DIR}/ffx_loop_loader.cpp")
        add_custom_command(OUTPUT "${loop_loader}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/ffx_create_context.py" "${ffx_loader}" "${loop_loader}"
            DEPENDS "${ffx_loader}" tools/ffx_create_context.py tools/ffx_version_query.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        set_source_files_properties("${loop_loader}" PROPERTIES HEADER_FILE_ONLY TRUE)
        target_sources(offscreen_check PRIVATE "${loop_loader}" tests/ffx_provider_loader.cpp)
        target_compile_definitions(offscreen_check PRIVATE FFX_LOOP_LOADER)
    endif()
endif()
if(EXISTS "${INTAKE_PYTHON}")
    # Startup stand-ins: exports, named traps and permissive answers (docs/startup-runtime.md).
    # Synchronous save reads after a restart; the second test commits through slots 28 and 29 first.
    add_test(NAME startup_gamesave_read COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gamesave_read_check.py"
        "$<TARGET_FILE:startup_gamesave_read>")
    set_tests_properties(startup_gamesave_read PROPERTIES TIMEOUT 30)
    add_test(NAME startup_gamesave_read_after_async_submit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gamesave_read_check.py" "$<TARGET_FILE:startup_gamesave_read>" write-async)
    set_tests_properties(startup_gamesave_read_after_async_submit PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
    foreach(scheduler IN ITEMS controlled system)
        add_test(NAME startup_gamesave_submit_${scheduler} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gamesave_submit_check.py" "$<TARGET_FILE:startup_gamesave_submit>" ${scheduler})
        set_tests_properties(startup_gamesave_submit_${scheduler} PROPERTIES TIMEOUT 30)
    endforeach()
    set_tests_properties(startup_gamesave_submit_system PROPERTIES SKIP_RETURN_CODE 77)
    foreach(scheduler IN ITEMS controlled system)
        add_test(NAME startup_gamesave_read_async_${scheduler} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gamesave_read_async_check.py" "$<TARGET_FILE:startup_gamesave_read_async>" ${scheduler})
        set_tests_properties(startup_gamesave_read_async_${scheduler} PROPERTIES TIMEOUT 30)
    endforeach()
    set_tests_properties(startup_gamesave_read_async_system PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME startup_stubs COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stub_check.py"
        "$<TARGET_FILE:startup_stub_consumer>" "${CMAKE_CURRENT_SOURCE_DIR}/src/startup_stubs"
        "$<TARGET_FILE:startup_stub_acphal>" "$<TARGET_FILE:startup_stub_chad>" "$<TARGET_FILE:startup_stub_xapu>"
        "$<TARGET_FILE:startup_stub_xcrdapi>" "$<TARGET_FILE:startup_stub_xg_xs>" "$<TARGET_FILE:startup_stub_gameinput>"
        "$<TARGET_FILE:xmem_shim>" "$<TARGET_FILE:d3d12_xs_shim>")
    set_tests_properties(startup_stubs PROPERTIES TIMEOUT 120)
    add_test(NAME startup_storage_directory_batch COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_storage_directory_batch.py" "$<TARGET_FILE:startup_stub_consumer>")
    set_tests_properties(startup_storage_directory_batch PROPERTIES TIMEOUT 30)
    # The stand-in's zlib decoder (src/startup_stubs/inflate.h) against CPython's zlib (#1149): stored,
    # fixed and dynamic blocks, a sync flush, and rejected short, truncated and out-of-window streams;
    # then seeded random streams against the bit-at-a-time build and a faulty-table control, and small
    # streams at every capacity and truncation against it and three fast-loop controls.
    add_test(NAME startup_inflate COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_inflate_check.py" "$<TARGET_FILE:startup_inflate_probe>"
        "$<TARGET_FILE:startup_inflate_probe_bitwise>" "$<TARGET_FILE:startup_inflate_probe_faulty>"
        "$<TARGET_FILE:startup_inflate_probe_faulty_margin>" "$<TARGET_FILE:startup_inflate_probe_faulty_input_margin>"
        "$<TARGET_FILE:startup_inflate_probe_faulty_distance>")
    set_tests_properties(startup_inflate PROPERTIES TIMEOUT 60)
    add_test(NAME startup_live_view COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_live_view_check.py")
    set_tests_properties(startup_live_view PROPERTIES TIMEOUT 60)
    add_test(NAME runtime_startup_live_view_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_live_view_cli_check.py")
    set_tests_properties(runtime_startup_live_view_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME startup_uniform_lane COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_uniform_lane_check.py")
    # NGG primitive-shader cases (#1723): identity triangle against single-change contrasts, reference model.
    add_test(NAME startup_ngg_slice COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_ngg_slice_check.py")
    add_test(NAME startup_image_sample_l COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_image_sample_l_check.py")
    add_test(NAME startup_image_sample_d COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_image_sample_d_check.py")
    # image_sample_d drawn on D3D12 (FXC 5_1 and DXC 6_0): GPU readback of the mip chosen by explicit gradients.
    add_test(NAME startup_image_sample_d_draw_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_d_draw_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_sample_d_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_d_draw_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_sample_d_draw_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME startup_image_gather_lz COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_image_gather_lz_check.py")
    add_test(NAME startup_compute_gather_lz COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_gather_lz_check.py")
    add_test(NAME startup_compute_image_store COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_image_store_check.py")
    add_test(NAME startup_compute_image_store_d16 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_image_store_d16_check.py")
    add_test(NAME startup_gfx2hlsl_heap_record COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_heap_record_check.py")
    add_test(NAME startup_gfx2hlsl_heap_word COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_heap_word_check.py")
    add_test(NAME startup_compute_readfirstlane COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_readfirstlane_check.py")
    add_test(NAME startup_compute_gather_l COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_gather_l_check.py")
    add_test(NAME startup_compute_buffer_atomics COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_buffer_atomics_check.py")
    add_test(NAME startup_image_sample_c COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_image_sample_c_check.py")
    add_test(NAME startup_image_gather_c_lz COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_image_gather_c_lz_check.py")
    # image_sample_b (#1996): translation controls, then a desktop draw whose mip level the bias selects.
    add_test(NAME startup_image_sample_b_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_image_sample_b_check.py")
    add_test(NAME startup_image_sample_lod_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_image_sample_lod_check.py")
    # Rewrites for instructions the host processor lacks (tools/startup/host_cpu.py), run on the host.
    add_test(NAME startup_host_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_host_cpu_check.py")
    set_tests_properties(startup_host_cpu PROPERTIES SKIP_RETURN_CODE 77)
    # The same switch in the startup debugger, on a probe that executes SHA-extension and RDPID instructions.
    add_test(NAME startup_host_cpu_debug COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_host_cpu_debug_check.py" "$<TARGET_FILE:startup_host_cpu_probe>")
    set_tests_properties(startup_host_cpu_debug PROPERTIES TIMEOUT 300)
    # tools/startup/capture.py against synthetic capture.bin files laid out like the writer's (#1149).
    add_test(NAME startup_capture COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_capture_check.py")
    add_test(NAME startup_capture_cli COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_capture_cli_check.py")
    # gfx2hlsl.py --capture terminates and refuses malformed pipeline records (wrapper cycles, short descs).
    add_test(NAME startup_gfx2hlsl_capture COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_capture_check.py")
    set_tests_properties(startup_gfx2hlsl_capture PROPERTIES TIMEOUT 120)
    # archive_requests.py writes runtime-keyed shader requests from a synthetic archive.
    add_test(NAME startup_archive_requests COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_archive_requests_check.py")
    set_tests_properties(startup_archive_requests PROPERTIES TIMEOUT 120)
    add_test(NAME startup_archive_requests_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_archive_requests_cli_check.py")
    # Two integer operations whose refusal was never reached: v_cvt_i32_f32 with an output
    # modifier, and v_readfirstlane_b32 without a proven uniform source.
    add_test(NAME startup_gfx2hlsl_op_refusals COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_op_refusals_check.py")
    set_tests_properties(startup_gfx2hlsl_op_refusals PROPERTIES TIMEOUT 60)
    # gfx2hlsl carries a descriptor pointer through s_add_u32 / s_addc_u32 with a literal offset (#1723).
    add_test(NAME startup_joined_table_pointer_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_joined_table_pointer_check.py")
    add_test(NAME startup_gfx2hlsl_desc_ptr_prop COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_desc_ptr_prop_check.py")
    set_tests_properties(startup_gfx2hlsl_desc_ptr_prop PROPERTIES TIMEOUT 60)
    # gfx2hlsl refuses a binary32 or integer vector operation with a source too few or too many.
    add_test(NAME startup_gfx2hlsl_operand_count COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_operand_count_check.py")
    # gfx2hlsl binary32 rounding (VEC_F floor, ceil, trunc, fract, rndne): translation controls, then a draw of
    # the translated pairs with reference words and one mutated lowering per operation.
    add_test(NAME startup_gfx2hlsl_float_round_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_float_round_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_float_round_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_float_round_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_float_round_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl refuses a scalar ALU operation whose operand list is too short.
    add_test(NAME startup_gfx2hlsl_scalar_arity COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_arity_check.py")
    # gfx2hlsl refuses a scalar ALU source list shorter than the template the scalar table spells (#2463).
    add_test(NAME startup_gfx2hlsl_scalar_table_arity COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_table_arity_check.py")
    # gfx2hlsl lowers v_swap_b32 (VOP1): CPU evaluation of the translated text, refusals of every form llvm-mc rejects.
    add_test(NAME startup_gfx2hlsl_swap COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_swap_check.py")
    # gfx2hlsl lowers s_bitcmp1_b32 and s_bitcmp0_b32 (SOPC): CPU evaluation of the translated SCC test.
    add_test(NAME startup_gfx2hlsl_s_bitcmp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_bitcmp_check.py")
    # gfx2hlsl lowers s_abs_i32 (SOP1, #1723): CPU evaluation, then a D3D12 UAV readback on
    # WARP/hardware (same dispatch pattern as startup_gfx2hlsl_s_ff1 / pack_absdiff).
    add_test(NAME startup_gfx2hlsl_s_abs COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_abs_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_s_abs_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_abs_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_s_abs_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl lowers s_quadmask_b64 (SOP1, #1723): CPU evaluation and refusals.
    add_test(NAME startup_gfx2hlsl_s_quadmask_b64 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_quadmask_b64_check.py")
    # gfx2hlsl lowers s_ff0_i32_b32 (SOP1, #1723): CPU evaluation and refusals.
    add_test(NAME startup_gfx2hlsl_s_ff0 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_ff0_check.py")
    # gfx2hlsl lowers s_bitset0_b32 and s_bitset1_b32 (SOP1, #2023 Item J): CPU evaluation and refusals.
    add_test(NAME startup_gfx2hlsl_s_bitset COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_bitset_check.py")
    # gfx2hlsl lowers s_flbit_i32_b32 (SOP1, #1723): CPU evaluation, then a D3D12 UAV
    # readback on WARP/hardware (same dispatch pattern as s_ff1 / s_abs / pack_absdiff).

    add_test(NAME startup_gfx2hlsl_s_flbit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_flbit_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_s_flbit_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_flbit_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_s_flbit_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl lowers s_ff1_i32_b32 of a general scalar and s_ff1_i32_b64 of a zero-extended
    # immediate (#2022 Item F); live SGPR-pair b64 is owned by open #2072. CPU evaluation, then
    # a D3D12 UAV readback on WARP/hardware (same dispatch pattern as pack_absdiff).
    add_test(NAME startup_gfx2hlsl_s_ff1 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_ff1_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_s_ff1_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_ff1_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_s_ff1_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl lowers s_quadmask_b32 (SOP1, #1723): CPU evaluation, then a D3D12 UAV
    # readback on WARP/hardware (same dispatch pattern as s_ff1 / s_abs / pack_absdiff).
    add_test(NAME startup_gfx2hlsl_s_quadmask COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_quadmask_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_s_quadmask_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_quadmask_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_s_quadmask_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl lowers v_cube{id,sc,tc,ma}_f32: device-free translation controls.
    add_test(NAME startup_gfx2hlsl_cube_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_cube_check.py")
    # gfx2hlsl.py --watch consumes only ready requests and does not retry an unchanged failure.
    add_test(NAME startup_gfx2hlsl_watch COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_watch_check.py")
    set_tests_properties(startup_gfx2hlsl_watch PROPERTIES TIMEOUT 120)
    add_test(NAME startup_gfx2hlsl_handler_arity COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_handler_arity_check.py")
    # gfx2hlsl names why s_getpc_b64 is refused instead of reporting the mnemonic alone.
    add_test(NAME startup_gfx2hlsl_getpc_refusal COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_getpc_refusal_check.py")
    # Image instructions with fewer than three operands (#2360 follow-up): the handler refused
    # them as an index error before it checked the count.
    add_test(NAME startup_gfx2hlsl_image_arity COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_image_arity_check.py")
    # gfx2hlsl lowers v_fma_mix_f32 and selects binary16 source halves on all three mixed-precision FMAs.
    add_test(NAME startup_gfx2hlsl_fma_mix COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_fma_mix_check.py")
    # VOP1/VOP2 sub-dword addressing (SDWA) in the translator (#1141), checked against the pixel AOT
    # lowering of the same selections.
    add_test(NAME startup_gfx2hlsl_sdwa COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sdwa_check.py")
    # 1D image sampling with an explicit level (#1721).
    add_test(NAME startup_gfx2hlsl_image_1d COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_image_1d_check.py")
    # Handlers that do not model a modifier they can receive refuse it (#1771).
    add_test(NAME startup_gfx2hlsl_modifier_free COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_modifier_free_check.py")
    # The src_scc scalar source (#1820).
    add_test(NAME startup_gfx2hlsl_src_scc COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_src_scc_check.py")
    # D3D12 UAV readback of s_cmp_eq_u32 + s_mov_b32 sX, src_scc on WARP/hardware vs the CPU reference,
    # with a mutated-lowering negative control (same dispatch pattern as s_ff1).
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_src_scc_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_src_scc_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_src_scc_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # src_scc at a branch target that one uniform SCC write reaches on every path.
    add_test(NAME startup_gfx2hlsl_src_scc_join COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_src_scc_join_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_src_scc_join_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_src_scc_join_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_src_scc_join_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # image_sample_c_lz with sampler word 2 bits 28-30 set (#1723).
    add_test(NAME startup_gfx2hlsl_sample_c_lz_mip COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sample_c_lz_mip_check.py")
    # The binary32 class comparison (#1795).
    add_test(NAME startup_gfx2hlsl_cmp_class COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_cmp_class_check.py")
    # The binary16 class comparison (#1855).
    add_test(NAME startup_gfx2hlsl_cmp_class_f16 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_cmp_class_f16_check.py")
    # The SDWA forms of the binary16 class comparison and their negative controls; the draws are registered below.
    add_test(NAME startup_gfx2hlsl_cmp_class_f16_sdwa COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_cmp_class_f16_sdwa_check.py")
    # The 16-bit vector ALU: add, sub, mul, min, max, fma forms and the i16/u16 conversions (#1723).
    add_test(NAME startup_gfx2hlsl_f16_alu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_f16_alu_check.py")
    # op_sel on a translated float operation is refused, not dropped (#1735).
    add_test(NAME startup_gfx2hlsl_opsel COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_opsel_check.py")
    # The 64-bit vector shifts (#1815).
    add_test(NAME startup_gfx2hlsl_b64_shift COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_b64_shift_check.py")
    # The scalar shift-and-add forms s_lshl1..4_add_u32 (Run 20 census #16).
    add_test(NAME startup_gfx2hlsl_s_lshl_add COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_lshl_add_check.py")
    # SOPK 16-bit immediates: s_movk_i32 and s_cmpk_*_i32 sign-extend, s_cmpk_*_u32 zero-extend.
    add_test(NAME startup_gfx2hlsl_sopk_signext COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sopk_signext_check.py")
    # s_brev_b32 of a known constant folds to a known word (a sampler built from it is a constant descriptor).
    add_test(NAME startup_gfx2hlsl_scalar_brev_fold COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_brev_fold_check.py")
    # A copy of a plain constant scalar register still assigns at run time and drops its constant at a join.
    add_test(NAME startup_gfx2hlsl_const_copy_join COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_const_copy_join_check.py")
    # v_pack_b32_f16 with op_sel and the neg/abs source modifiers, evaluated against a bit reference.
    add_test(NAME startup_gfx2hlsl_pack_b32_f16 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_pack_b32_f16_check.py")
    # Scalar sign-extends and conditional moves (batch 3 #2).
    add_test(NAME startup_gfx2hlsl_s_sext_cmov COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_s_sext_cmov_check.py")
    # s_bfm_b64 (#1723).
    add_test(NAME startup_gfx2hlsl_bfm_b64 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_bfm_b64_check.py")
    # SDWA forms of the float-result conversions (#1727).
    add_test(NAME startup_gfx2hlsl_sdwa_cvt COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sdwa_cvt_check.py")
    # The SDWA form of v_cndmask_b32: fixture and model controls; the draws are registered below.
    add_test(NAME startup_gfx2hlsl_sdwa_cndmask COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sdwa_cndmask_check.py")
    # VOPC SDWA compares (#1906): every integer compare, select and sext() evaluated against an integer
    # reference; floating-point SDWA forms and unsupported modifiers are refused. The draws are registered below.
    add_test(NAME startup_gfx2hlsl_vopc_sdwa COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_vopc_sdwa_check.py")
    add_test(NAME startup_gfx2hlsl_draw_skip COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_draw_skip_check.py")
    # DPP16 quad pair broadcasts (#2125 item C): translation controls, a CPU quad model of the emitted text and the
    # refusals of every other DPP control. The draws are registered below.
    add_test(NAME startup_gfx2hlsl_dpp_pair COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_pair_check.py")
    # DPP16 quad reads in a pixel program with a uniform loop and branch: the whole-program convergence proof and its
    # refusals (vccz loop, SCC from a lane mask, EXEC write reaching the read, late s_wqm). The draws are below.
    add_test(NAME startup_gfx2hlsl_dpp_quad_flow COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_quad_flow_check.py")
    # DPP16 quad broadcasts quad_perm:[k,k,k,k] (#2125): lowered to QuadReadLaneAt, so the pixel stage compiles as
    # ps_6_0; the controls and refusals run here, the draws below compare every pixel with a CPU reference.
    add_test(NAME startup_gfx2hlsl_dpp_quad_broadcast COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_quad_broadcast_check.py")
    # f32 lg/nlg ordered for NaN (#1920): every f32 condition, e32 and e64 under every neg/abs, evaluated over
    # +-0, denormals, +-1, +-max, +-inf and NaNs against the ISA reference; the old != lowering must fail.
    add_test(NAME startup_gfx2hlsl_f32_lg COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_lg_check.py")
    # exp null (#1723, Run 20 census #11): the null export writes nothing and keeps the vm discard.
    add_test(NAME startup_gfx2hlsl_export_null COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_export_null_check.py")
    # Draw a colour export followed by exp null: the null writes no channel, and a control that writes
    # mrt0 from the null site must produce a pixel mismatch (#1723).
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_export_null_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_export_null_draw_check.py" draw
            "${DXC_EXECUTABLE}" "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_export_null_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # f32 nlt/nle/ngt/nge, o and u hold under FXC's and DXC's rewrites of float compares without -Gis (#1936).
    add_test(NAME startup_gfx2hlsl_f32_nan COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_nan_check.py")
    # f32 SDWA compares (#1906): DWORD selections emit the e64 text and equal the ISA reference over the same 256 pairs
    # under the IEEE, FXC and DXC models; every byte/word selection is refused; the text before #1930/#1949 must fail.
    add_test(NAME startup_gfx2hlsl_f32_sdwa COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_sdwa_check.py")
    # A negated source on the vector select flips that source's sign bit (#1709).
    add_test(NAME startup_gfx2hlsl_cndmask_neg COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_cndmask_neg_check.py")
    # The neg(x) spelling of the sign modifier is the same sign flip as -x (#1723).
    add_test(NAME startup_gfx2hlsl_neg_operand COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_neg_operand_check.py")
    set_tests_properties(startup_gfx2hlsl_neg_operand PROPERTIES TIMEOUT 60)
    # Vertex-stage buffer stores lower to RWByteAddressBuffer Store* under manifest version 2 (#1723).
    add_test(NAME startup_gfx2hlsl_buffer_store COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_buffer_store_check.py")
    # Output modifiers on float-result conversions (#1705).
    add_test(NAME startup_gfx2hlsl_vcvt_omod COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_vcvt_omod_check.py")
    # A typed buffer load of BUF_FMT_16_16_16_16_FLOAT reads four halves from one 8-byte element (#1695).
    add_test(NAME startup_gfx2hlsl_tbuffer_16f COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_tbuffer_16f_check.py")
    # A typed buffer load of BUF_FMT_2_10_10_10_UNORM reads three 10-bit fields and a 2-bit one from one dword (#1723).
    add_test(NAME startup_gfx2hlsl_tbuffer_2101010 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_tbuffer_2101010_check.py")
    # The draw's DXGI -> FORMAT table for typed views read by buffer_load_format_* matches the translation's switch.
    add_test(NAME startup_buffer_format_word3_table COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_buffer_format_word3_table_check.py")
    # 32-bit scalar complement logic: s_nand_b32, s_nor_b32 and s_xnor_b32 against an integer reference (#1919).
    add_test(NAME startup_gfx2hlsl_sop2_complement COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sop2_complement_check.py")
    # s_waitcnt_depctr is a hazard delay without architectural effect: the translation is unchanged by it (#2413).
    add_test(NAME startup_gfx2hlsl_waitcnt_depctr COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_waitcnt_depctr_check.py")
    # Slot 57 mesh requests (#2413): the one accepted group-memory shape translates; each mutation is refused.
    add_test(NAME startup_mesh57_skeleton COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mesh57_skeleton_check.py")
    # Slot 57 mesh with a depth-only pixel stage (#2413 T5): the null export keeps its discard, no colour target.
    add_test(NAME startup_mesh57_depth_only COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mesh57_depth_only_check.py")
    # Slot 57 mesh loop refusal outside the accepted exchanges (#2413 T6); mutant drops the back-edge.
    add_test(NAME startup_mesh57_loop_refusal COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mesh57_loop_refusal_check.py")
    # Slot 57 mesh constant-trip loop lowering outside the accepted exchanges (#2413 T6).
    add_test(NAME startup_mesh57_loop COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mesh57_loop_check.py")
    # Slot 57 constant-lane v_writelane_b32 / v_readlane_b32 spill idiom (#2413 T7).
    add_test(NAME startup_mesh57_lane_spill COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mesh57_lane_spill_check.py")
    # Scalar SOPK accumulate: s_addk_i32 signed-overflow SCC and s_mulk_i32 against an integer reference.
    add_test(NAME startup_gfx2hlsl_sopk_accum COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sopk_accum_check.py")
    # s_pack_ll_b32_b16, s_pack_lh_b32_b16 and s_absdiff_i32 against an integer reference (#1723); the _warp/_hardware tests also draw them (D3D12 readback).
    add_test(NAME startup_gfx2hlsl_pack_absdiff COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_pack_absdiff_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_pack_absdiff_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_pack_absdiff_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_pack_absdiff_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl run-time sampler heap indexing (#1143): translation controls, then a desktop draw with
    # DXC ps_6_0 and, when the Windows SDK's FXC is found, the ps_5_1 the startup tools compile with.
    find_program(STARTUP_FXC fxc HINTS "${DXC_BIN_DIR}")
    if(STARTUP_FXC)
        # The v_fma_mix* translations from startup_gfx2hlsl_fma_mix, compiled for ps_5_1.
        add_test(NAME startup_gfx2hlsl_fma_mix_fxc COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_fma_mix_check.py" fxc "${STARTUP_FXC}")
    endif()
    # gfx2hlsl conversion operations: translation controls, then a draw of the translated pairs with
    # reference words and one mutated lowering per operation (v_cvt_f16_f32 through DXC only).
    # Compute translator: integer inequality lane guards.
    add_test(NAME compute_alu_cmp_ne_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compute_alu_cmp_ne_check.py")
    add_test(NAME startup_gfx2hlsl_cvt_alu_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_alu_check.py")
    # Compute translator: scalar pair population count.
    add_test(NAME compute_alu_bcnt64_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compute_alu_bcnt64_check.py")
    # Compute translator: buffer_load_format with the format read from V# word 3 at run time.
    add_test(NAME compute_load_format_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compute_load_format_check.py" controls)
    # Compute translator: buffer_load_format with the V# taken from a run-time heap view record.
    add_test(NAME compute_heap_view_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compute_heap_view_check.py" controls)
    add_test(NAME compute_heap_store_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compute_heap_store_check.py" controls)
    add_test(NAME compute_desc_numeric_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compute_desc_numeric_check.py" controls)
    add_test(NAME compute_alu_lane_gaps_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compute_alu_lane_gaps_check.py" controls)
    # Startup shader translator: signed and unsigned three-source integer min, max and median.
    add_test(NAME startup_gfx2hlsl_int_med3_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_int_med3_check.py")
    # v_med3_f32 with a NaN source is the minimum of the three (ISA p. 343): the preamble's med3_32 tests the
    # encoding, the integer medians are unchanged, and the old branchless helper must be rejected.
    add_test(NAME startup_gfx2hlsl_f32_med3_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_med3_check.py")
    # The same four words drawn on WARP and the card, the NaN among them from the entry constants; the
    # branchless lowering must mismatch on that lane.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_f32_med3_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_med3_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_f32_med3_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77)
    endforeach()
    # Startup shader translator: s_cselect_b32 into the wave32 lane masks vcc_lo and exec_lo.
    add_test(NAME startup_gfx2hlsl_cselect_mask_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cselect_mask_check.py")
    # Startup shader translator: a scalar load or select into a former lane-mask SGPR clears its mask mark.
    add_test(NAME startup_gfx2hlsl_mask_overwrite_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mask_overwrite_check.py")
    # Startup shader translator: lane masks cannot be used as vector data words.
    add_test(NAME startup_gfx2hlsl_mask_data_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mask_data_check.py")
    # Startup shader translator: a plain image_sample past a uniform join keeps its implicit LOD (Sample, not level 0).
    add_test(NAME startup_image_sample_implicit_lod_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_implicit_lod_check.py")
    # Startup shader translator: image_get_lod on a 2D texture (CalculateLevelOfDetail / Unclamped).
    add_test(NAME startup_gfx2hlsl_image_get_lod_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_image_get_lod_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_get_lod_view_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_get_lod_view_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_image_get_lod_view_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # Startup shader translator: v_add/sub/subrev_co_u32 against ISA references.
    add_test(NAME startup_gfx2hlsl_add_sub_co_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_add_sub_co_check.py")
    # Startup shader translator: v_{add,sub,subrev}_co_ci_u32 carry/borrow-in and out.
    add_test(NAME startup_gfx2hlsl_add_sub_co_ci_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_add_sub_co_ci_check.py")
    # Startup shader translator: s_*_saveexec with D == S0 reads S0 before writing D.
    add_test(NAME startup_gfx2hlsl_saveexec_same_reg_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_saveexec_same_reg_check.py")
    # Startup shader translator: a VOPC compare into vcc_hi, exec_hi or m0 is refused, not a crash.
    add_test(NAME startup_gfx2hlsl_compare_dst_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compare_dst_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_cvt_alu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_alu_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cvt_alu_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_cvt_pk_u8_f32 (#2023 item K): translation controls, then a draw of the translated pairs with
    # reference words and a mutated lowering that loses S2.
    add_test(NAME startup_gfx2hlsl_cvt_pk_u8_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_pk_u8_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_cvt_pk_u8_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_pk_u8_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cvt_pk_u8_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_pack_b32_f16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_pack_b32_f16_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_pack_b32_f16_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_cvt_pk_u16_u32 and v_cvt_pk_i16_i32 (#1723): VOP3A saturating 16-bit integer packs, encoding/refusal
    # controls, and WARP/hardware draws (FXC 5_1 and DXC 6_0) with four mutations per opcode.
    add_test(NAME startup_gfx2hlsl_cvt_pk_int16_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_pk_int16_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_cvt_pk_int16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_pk_int16_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cvt_pk_int16_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl RDNA 2 scalar null operand (code 125) and Stage.scalar destination guards (#2618, #1723, #2463):
    # 32-bit null-destination SCC updates, null source (0u), explicit Unsupported refusals replacing TypeError, and
    # WARP/hardware draws + root-constant buffer readbacks with negative controls.
    add_test(NAME startup_gfx2hlsl_scalar_null_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_null_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_scalar_null_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_null_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_scalar_null_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl compute 32-bit GLOBAL saddr load (global_load_dword vdst, vaddr, s[base:base+1] [offset:imm]) (#2618, #2022):
    # proven 64-bit root buffer pointer pairs (direct, copied, literal-advanced), signed 12-bit immediate offsets,
    # check_encoding unused-bit guards, refusals, and WARP/hardware compute readbacks with negative mutations.
    add_test(NAME startup_compute_global_load_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_compute_global_load_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_global_load_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_global_load_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_global_load_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_cvt_off_f32_i4 (VOP1 0x0e and VOP3A 0x18e): signed 4-bit nibble conversion with output modifiers,
    # low16_only provenance, uniformity tracking, refusals, and WARP/hardware draws with mutated controls.
    add_test(NAME startup_gfx2hlsl_cvt_off_f32_i4_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_off_f32_i4_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_cvt_off_f32_i4_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cvt_off_f32_i4_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cvt_off_f32_i4_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl 16-bit integer VOPC compares (v_cmp/v_cmpx _i16/_u16, #1723): translation controls, then draws of a
    # census-shaped v_cmpx kill and of every condition folded into mask words, with mutated lowerings.
    add_test(NAME startup_gfx2hlsl_cmp16_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cmp16_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_cmp16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cmp16_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cmp16_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME startup_sampler_heap_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_sampler_heap_check.py")
    add_test(NAME startup_vertex_fetch_formats_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_vertex_fetch_formats_check.py" controls)
    add_test(NAME startup_buffer_address_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_buffer_address_check.py" controls)
    add_test(NAME startup_smem_address_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_smem_address_check.py" controls)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_r8_uint_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_r8_uint_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_r8_uint_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        # Every buffer format of the gfx2hlsl vertex-fetch table, read back through the same compute wrapper.
        add_test(NAME startup_vertex_fetch_formats_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_vertex_fetch_formats_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_vertex_fetch_formats_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_buffer_address_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_buffer_address_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_buffer_address_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_smem_address_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_smem_address_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_smem_address_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_sampler_heap_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_sampler_heap_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_sampler_heap_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_sampler_heap_wrapped_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_sampler_heap_check.py" wrapped "$<TARGET_FILE:d3d12_xs_shim>" ${adapter})
        set_tests_properties(startup_sampler_heap_wrapped_${adapter} PROPERTIES TIMEOUT 30
            ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_D3D12_DEBUG=1")
    endforeach()
    # gfx2hlsl 3D image sampling (#1149): translation controls, then a desktop draw that names the texel.
    add_test(NAME startup_image_3d_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_3d_check.py")
    add_test(NAME startup_image_load_mip_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_load_mip_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_3d_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_3d_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_3d_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_gfx2hlsl_image_1d_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_image_1d_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_image_1d_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_image_load_mip_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_load_mip_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_image_load_mip_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl pixel-stage image_store (#1996 item F): translation controls and refusals, then a desktop draw
    # that reads every texel of the stored image back.
    add_test(NAME startup_pixel_image_store_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_pixel_image_store_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_pixel_image_store_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_pixel_image_store_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_pixel_image_store_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl 2D array images: translation controls, then a desktop draw that names the slice's texel.
    add_test(NAME startup_image_2d_array_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_2d_array_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_2d_array_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_2d_array_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_2d_array_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl packed 2D A16 image_sample / image_sample_lz coordinates and modifier validation.
    add_test(NAME startup_image_sample_a16_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_a16_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_sample_a16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_a16_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_sample_a16_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl comparison sampling with CLAMP_BORDER and fixed border colors (#2023 item F).
    add_test(NAME startup_image_sample_c_border_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_c_border_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_sample_c_border_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_c_border_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_sample_c_border_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_sample_b_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_b_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_sample_b_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl image_sample_b past a divergent EXEC: EXEC branches decided per quad, drawn against a CPU reference.
    add_test(NAME startup_image_sample_b_flow_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_b_flow_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_sample_b_flow_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_b_flow_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_sample_b_flow_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl image_get_lod past a divergent EXEC: EXEC branches decided per quad, drawn against a CPU reference.
    add_test(NAME startup_image_get_lod_flow_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_get_lod_flow_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_get_lod_flow_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_get_lod_flow_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_get_lod_flow_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # Constant-sampler LOD limits of image_sample, _l and _lz (#2177): each form drawn alone against a plain-smp control.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_sample_lod_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_lod_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_sample_lod_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_sample_implicit_lod_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_sample_implicit_lod_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_sample_implicit_lod_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl level-zero D16 image_load narrowing and pairwise packing (#2023).
    add_test(NAME startup_image_load_d16_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_image_load_d16_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_image_load_d16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_load_d16_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_load_d16_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # Build revision generator in temporary repositories: clean commit, no rewrite of an unchanged file,
    # untracked-only, tracked edit, new commit, not a repository, a directory inside another repository,
    # an inherited GIT_DIR and no git executable.
    add_test(NAME startup_build_rev_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_build_rev_check.py")
    set_tests_properties(startup_build_rev_controls PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    # The built shim holds the generated revision and the window-title and log formats that print it.
    add_test(NAME startup_build_rev_dll COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_build_rev_check.py" dll "$<TARGET_FILE:d3d12_xs_shim>"
        "${x2w_build_rev_source}")
    set_tests_properties(startup_build_rev_dll PROPERTIES TIMEOUT 60)
    # gfx2hlsl flat parameters keep the exported words (#1259): translation controls, then a desktop
    # draw of the translated pair with FXC 5_1 (the --pending path) and DXC 6_0.
    add_test(NAME startup_flat_param_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_flat_param_check.py")
    # The pixel input mask scan finds where a pipeline stores the two masks, from shader register use (#1629).
    add_test(NAME startup_ps_input_scan COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_ps_input_scan_check.py")
    add_test(NAME startup_ps_input_scan_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_ps_input_scan_cli_check.py")
    # The pixel input masks come from the captured stream description of the exact pipeline (#1629): a decoy
    # description, stale or missing masks and contradictory enable/address masks; then the #1634 gradient draw.
    add_test(NAME startup_packed_screen_position_provenance COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_packed_position_provenance_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_packed_screen_position_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_packed_position_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_packed_screen_position_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_packed_screen_position_provenance_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_packed_position_provenance_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_packed_screen_position_provenance_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_flat_param_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_flat_param_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_flat_param_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME raster_winding_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/raster_winding_reference.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(raster_winding_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # s_bcnt0/1_i32_b32/b64, s_ff0/ff1_i32_b64 and s_flbit_i32_b64/i64 against an integer reference (#1723); the _warp/_hardware tests also draw them (D3D12 readback).
    add_test(NAME startup_gfx2hlsl_s_bit_scan COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_s_bit_scan_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_s_bit_scan_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_s_bit_scan_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_s_bit_scan_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl three-source integer vector operations (VEC_U): translation controls, then a draw of the translated
    # pairs with reference words and one mutated lowering per operation.
    add_test(NAME startup_gfx2hlsl_int3_alu_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_int3_alu_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_int3_alu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_int3_alu_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_int3_alu_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl per-lane bit operations: CPU evaluation of the translated text against an independent
    # reference with mutation controls, then a desktop draw of the translated pairs (FXC 5_1 and DXC 6_0).
    add_test(NAME startup_gfx2hlsl_bit_alu_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_bit_alu_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_bit_alu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_bit_alu_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_bit_alu_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # s_bfm_b64 read back on a desktop adapter: widths 0/1/31/32/33/63 x offsets 0/1/31/32/63 from run-time root
    # constants against the bit-loop reference (FXC 5_1 and DXC 6_0), with an uncapped reference and a mutated lowering
    # that the draw must reject. The startup_gfx2hlsl_bfm_b64 test above holds the CPU controls.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_bfm_b64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_bfm_b64_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_bfm_b64_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl two- and one-source integer vector operations (VEC_U): translation controls, then the same draw
    # of the translated pairs with reference words and one mutated lowering per operation.
    add_test(NAME startup_gfx2hlsl_int_alu_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_int_alu_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_int_alu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_int_alu_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_int_alu_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl abs (`|src|` and `-|src|`) on v_cndmask_b32_e64 data sources: CPU evaluation of the translated
    # text over 32-bit bit patterns, then a desktop draw of the translated pair (FXC ps_5_1 and DXC ps_6_0)
    # with order-reversed and abs-dropped mutation controls.
    add_test(NAME startup_gfx2hlsl_cndmask_abs_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cndmask_abs_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_cndmask_abs_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cndmask_abs_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cndmask_abs_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_cube{id,sc,tc,ma}_f32: the source-built cube directions are drawn and compared with the
    # LLVM ConstantFoldAMDGCNCubeIntrinsic model; swapped id/sc, tie-order and cubema-factor controls must fail.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_cube_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cube_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cube_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_interp_p1ll_f16 / v_interp_p2_f16 (#1996): translation controls with a high-half inversion
    # control, then a desktop draw of the translated pair with DXC 6_0.
    add_test(NAME startup_gfx2hlsl_interp_f16_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_interp_f16_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_interp_f16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_interp_f16_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_interp_f16_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_interp_p2_f16 with op_sel 0x8 (destination high half, #2413 item T9): CPU reference and mutations.
    add_test(NAME startup_gfx2hlsl_interp_p2_hi_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_interp_p2_hi_check.py")
    # gfx2hlsl DPP16 pair broadcasts: each of the four quad_perm patterns is drawn over 16 x 16 pixels with a different
    # word per pixel and compared with a CPU reference (#2125 item C); lane mutations must fail; compiled with DXC ps_6_0.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_dpp_pair_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_pair_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_dpp_pair_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl DPP16 quad reads (swap, broadcast, pair) inside a uniform scalar loop with an if: 16 x 16 pixels against
    # a CPU reference of the per-pass neighbour words; a read taking the wrong lane must fail. DXC ps_6_0 only.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_dpp_quad_flow_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_quad_flow_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_dpp_quad_flow_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl lowers DPP16 quad swaps (quad_perm [1,0,3,2], [2,3,0,1], [3,2,1,0]) in a pixel stage to QuadReadAcross*.
    add_test(NAME startup_gfx2hlsl_dpp_quad_swap_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_quad_swap_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_dpp_quad_swap_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_quad_swap_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_dpp_quad_swap_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl lowers constant-lane SGPR spills (v_writelane_b32 / v_readlane_b32) in a pixel stage to scalar slots (#2125 item E).
    add_test(NAME startup_gfx2hlsl_sgpr_spill_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sgpr_spill_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_sgpr_spill_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sgpr_spill_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_sgpr_spill_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # The same spill slots on wave64 lanes 32..63 and in a vertex stage (k and k + 32 on one VGPR refused).
    add_test(NAME startup_gfx2hlsl_spill_wave64_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_spill_wave64_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_spill_wave64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_spill_wave64_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_spill_wave64_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # wave32 vcc_hi as an ordinary scalar register (compare/carry destination, mask, scalar operand) when the program
    # proves it; the 64-bit vcc pair, an unproven VALU vcc_lo write and exec_hi writes are refused, not crashes.
    add_test(NAME startup_gfx2hlsl_vcc_hi_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_vcc_hi_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_vcc_hi_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_vcc_hi_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_vcc_hi_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl 24-bit multiplies, v_xnor_b32 and the funnel shifts: CPU evaluation of the translated text
    # against an independent reference built from unbounded integers.
    add_test(NAME startup_gfx2hlsl_mul24_align COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul24_align_check.py")
    set_tests_properties(startup_gfx2hlsl_mul24_align PROPERTIES TIMEOUT 120)
    # The same lowerings drawn on D3D12 (FXC 5_1 and DXC 6_0), GPU readback against the same reference.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_mul24_align_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul24_align_draw_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_mul24_align_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # The same spill slots across branches: a write must reach the read on every path, outside non-uniform regions.
    add_test(NAME startup_gfx2hlsl_spill_branches COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_spill_branches_check.py")
    # The same branches drawn on D3D12 (FXC 5_1 and DXC 6_0): two uniform choices write different words to one slot,
    # GPU readback of the reload after the join against each arm's reference, the opposite arm as a negative control.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_spill_branches_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_spill_branches_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_spill_branches_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl 16-bit vector ALU (#1723): the translated pairs drawn on WARP and hardware (FXC 5_1 and DXC 6_0),
    # four result words per draw against an exact binary16 reference.
    add_test(NAME startup_gfx2hlsl_f16_alu_draw_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_f16_alu_draw_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_f16_alu_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_f16_alu_draw_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_f16_alu_draw_${adapter} PROPERTIES TIMEOUT 900 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_cmpx_le_i32_sdwa on a sign-extended byte decides which of 16 x 16 pixels survive, checked
    # pixel by pixel (#1906); translations without the select or without sext() must fail the same draw.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_vopc_sdwa_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_vopc_sdwa_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_vopc_sdwa_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_gfx2hlsl_cmp_class_f16_sdwa_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_cmp_class_f16_sdwa_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_cmp_class_f16_sdwa_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_gfx2hlsl_dpp_quad_broadcast_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_dpp_quad_broadcast_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_dpp_quad_broadcast_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_gfx2hlsl_sdwa_cvt_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sdwa_cvt_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_sdwa_cvt_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        # Four SDWA v_cndmask_b32 selects over 16 x 16 pixels against a bit model; six mutated selects must fail.
        add_test(NAME startup_gfx2hlsl_sdwa_cndmask_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sdwa_cndmask_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_sdwa_cndmask_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_cmp/v_cmpx lg and nlg f32 over every pair of +-0, denormal, +-1, +-max, +-inf and NaN words decide
    # 16 x 16 pixels, checked pixel by pixel (#1920); the old != lowering must fail the same draws.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_f32_lg_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_lg_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_f32_lg_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # Every lowered f32 condition but lg/nlg decides 16 x 16 pixels with FXC and DXC, checked pixel by pixel (#1936);
    # the text before #1936 must fail on the compiler that rewrote it and match that rewrite's image.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_f32_nan_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_nan_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_f32_nan_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # Every f32 condition in its DWORD SDWA form decides 16 x 16 pixels with default-flag FXC and DXC, checked pixel
    # by pixel (#1906); the text before #1930/#1949 must fail on the compiler that broke it.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_f32_sdwa_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_f32_sdwa_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_f32_sdwa_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME startup_gfx2hlsl_mad_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mad_check.py")
    add_test(NAME shader_signed_zero_minmax_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/shader_signed_zero_minmax_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME shader_signed_zero_minmax_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/shader_signed_zero_minmax_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(shader_signed_zero_minmax_${adapter} PROPERTIES TIMEOUT 240 SKIP_RETURN_CODE 77)
    endforeach()
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_mad_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mad_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        add_test(NAME startup_gfx2hlsl_mad_preserve_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mad_check.py" preserve "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_mad_dispatch_${adapter} startup_gfx2hlsl_mad_preserve_${adapter}
            PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_mad_u32_u16: low-16 unsigned multiply-add with 32-bit addend and wraparound.
    add_test(NAME startup_gfx2hlsl_mad_u32_u16_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mad_u32_u16_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_mad_u32_u16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mad_u32_u16_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_mad_u32_u16_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_fma_mix*: every translated form dispatched against a CPU reference that decodes the VOP3P
    # word itself, plus a control that drops the high-half shift.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_fma_mix_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_fma_mix_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_fma_mix_dispatch_${adapter}
            PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME startup_gfx2hlsl_neg_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_neg_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_neg_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_neg_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_neg_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl compute buffer_store_format_d16_x: multi-format, bounds/OOB, atomic CAS RMW and EXEC guard (Refs #2274).
    add_test(NAME startup_compute_store_d16_x_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_compute_store_d16_x_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_store_d16_x_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_store_d16_x_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_store_d16_x_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS f32-drop-store f32-wrong-half f32-drop-oob unorm16-trunc p-drop-soffset p-drop-keep s-fold-soff-stride e-drop-exec b-short-binding b-tight-host-guard)
            add_test(NAME startup_compute_store_d16_x_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_compute_store_d16_x_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_compute_store_d16_x_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl compute buffer_store_format_xyzw: 4-channel formats, bounds/OOB, channel-count no-op and EXEC guard (Refs #2274).
    add_test(NAME startup_compute_store_format_xyzw_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_compute_store_format_xyzw_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_store_format_xyzw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_store_format_xyzw_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_store_format_xyzw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS x-drop-store x-swap-xy x-drop-index-oob unorm8-trunc unorm10-w-scale f16-drop-odd mismatch-writes r-drop-soffset e-drop-exec)
            add_test(NAME startup_compute_store_format_xyzw_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_compute_store_format_xyzw_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_compute_store_format_xyzw_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl compute stage: entry registers, numthreads and the offen buffer store, dispatched on a plain device (#1412).
    add_test(NAME startup_gfx2hlsl_compute_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_check.py")
    # The GPU check package replays these cases on a contributor's adapter (tools/record_gpu_cases.py).
    add_test(NAME gpu_case_recorder COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/gpu_case_recorder_check.py" "${DXC_EXECUTABLE}")
    set_tests_properties(gpu_case_recorder PROPERTIES TIMEOUT 300)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_compute_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_compute_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_gfx2hlsl_compute_mbcnt_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_check.py" control mbcnt "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_compute_mbcnt_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS swapped-axes dropped-store b-offset c-unpredicated f-peer f-broadcast f-second-fill g-swapped-offsets g-overlap
                j-scalar-dropped h-inner-unpredicated k-block-entered m-else-unswitched n-unmasked o-mask-kept
                n-dropped-broadcast p-dropped-andn2 p-dropped-or p-block-entered q-block-entered q-not-all-ones
                s-min-strict s-borrow-flipped)
            add_test(NAME startup_gfx2hlsl_compute_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_gfx2hlsl_compute_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl constant-lane SGPR spills of descriptor and pointer words in compute stages, across branches (#1723).
    add_test(NAME startup_gfx2hlsl_compute_spill_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_spill_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_compute_spill_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_spill_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_compute_spill_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS s-arm-swapped s-store-dropped p-store-dropped)
            add_test(NAME startup_gfx2hlsl_compute_spill_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_spill_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_gfx2hlsl_compute_spill_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl constant-lane SGPR spills of lane masks in compute stages (#1723).
    add_test(NAME startup_gfx2hlsl_compute_mask_spill_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_mask_spill_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_compute_mask_spill_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_mask_spill_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_compute_mask_spill_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS m-saveexec-dropped m-mask-inverted v-branch-inverted)
            add_test(NAME startup_gfx2hlsl_compute_mask_spill_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_compute_mask_spill_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_gfx2hlsl_compute_mask_spill_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl v_mad_u64_u32 / v_mad_i64_i32: helper math against a 64-bit reference, carry-out mask, refusals (Part of #1723).
    add_test(NAME startup_gfx2hlsl_mad64 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mad64_check.py")
    set_tests_properties(startup_gfx2hlsl_mad64 PROPERTIES TIMEOUT 60)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_mad64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mad64_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_mad64_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl bounded 64-bit LDS exchanges (ds_write_b64, ds_read_b64) across s_barrier (Refs #2274, #1541).
    add_test(NAME startup_compute_lds_b64_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_b64_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_lds_b64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_b64_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_lds_b64_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS p-same-lane p-swap-dwords p-drop-high b-wrong-mask b-wrong-lane)
            add_test(NAME startup_compute_lds_b64_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_b64_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_compute_lds_b64_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl COMPUTE_PGM_RSRC2.TG_SIZE_EN wave-ID masking for single-wave groups <= 32 threads (Refs #2274).
    add_test(NAME startup_compute_tg_size_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_compute_tg_size_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_tg_size_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_tg_size_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_tg_size_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS dropped-base swapped-mask)
            add_test(NAME startup_compute_tg_size_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_compute_tg_size_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_compute_tg_size_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl bounded 128-bit LDS exchanges (ds_write_b128, ds_read_b128) and mixed 32/64/128-bit ops (Refs #1541).
    add_test(NAME startup_compute_lds_b128_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_b128_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_lds_b128_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_b128_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_lds_b128_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS q-same-lane q-swap-dwords q-drop-fourth b-wrong-mask m-wrong-b64-off r-wrong-mask)
            add_test(NAME startup_compute_lds_b128_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_b128_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_compute_lds_b128_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # gfx2hlsl 64-bit VOP3 shifts: binary round-trip, overlap, guards and WARP/hardware draws (Refs #1723).
    add_test(NAME startup_gfx2hlsl_shift64_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_shift64_check.py")
    add_test(NAME startup_gfx2hlsl_shift64_literal COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_shift64_literal_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_shift64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_shift64_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_shift64_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl signed multiply-high (v_mul_hi_i32, s_mul_hi_i32): helper math, refusals, mutations and draws.
    add_test(NAME startup_gfx2hlsl_mul_hi_i32_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul_hi_i32_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_mul_hi_i32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul_hi_i32_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_mul_hi_i32_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_fract_f32 goes through the clamped fract32 helper, never a bare D3D frac (#1741).
    add_test(NAME startup_gfx2hlsl_fract COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_fract_check.py")
    set_tests_properties(startup_gfx2hlsl_fract PROPERTIES TIMEOUT 60)
    # The same cap drawn on one pixel with FXC 5_1 (where the float comparison it used to be written with
    # folded away) and DXC 6_0; the uncapped pair must read 0x3f800000 on the -2^-30 lane.
    add_test(NAME startup_gfx2hlsl_fract_draw_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_fract_draw_check.py")
    set_tests_properties(startup_gfx2hlsl_fract_draw_controls PROPERTIES TIMEOUT 60)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_fract_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_fract_draw_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_fract_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl signed 24-bit multiply/multiply-add (v_mul_i32_i24, v_mad_i32_i24): evaluator, refusals and draws.
    add_test(NAME startup_gfx2hlsl_mul_mad_i24_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul_mad_i24_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_mul_mad_i24_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul_mad_i24_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_mul_mad_i24_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl s_load into s[104:107] followed by a vcc compare and select: WARP/hardware draw vs CPU reference (Refs #1723).
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_sload_s104_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sload_s104_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_sload_s104_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_gfx2hlsl_desc_vcc_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_desc_vcc_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_desc_vcc_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl dual-offset/stride-64 32-bit LDS ops and 32-bit LDS atomics (Refs #1541, #2274).
    add_test(NAME startup_compute_lds_dual_atomics_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_dual_atomics_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_lds_dual_atomics_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_dual_atomics_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_lds_dual_atomics_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS d-wrong-st64-stride d-drop-oob-zero d-drop-align d-drop-exec d-alias-overwrite
                a-swap-minmax a-drop-exec a-drop-wrxchg-rtn a-oob-nonzero r-drop-add-rtn)
            add_test(NAME startup_compute_lds_dual_atomics_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/startup_compute_lds_dual_atomics_check.py" control ${control} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(startup_compute_lds_dual_atomics_${control}_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                PASS_REGULAR_EXPRESSION "control ${control}: rejected at word=[0-9]+ ")
        endforeach()
    endforeach()
    # XG slots 2 and 8 for a texture given the 4 KiB allocation answer (src/startup_stubs/small_texture_4k.h):
    # the copy must stay in front of a guard page; the mutated run is not limited and must fail.
    add_test(NAME startup_small_texture_4k_xg COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_small_texture_4k_xg_check.py" "$<TARGET_FILE:startup_stub_xg_xs>")
    add_test(NAME startup_small_texture_4k_xg_no_limit_control COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_small_texture_4k_xg_check.py" "$<TARGET_FILE:startup_stub_xg_xs>" --mutate no-limit)
    set_tests_properties(startup_small_texture_4k_xg startup_small_texture_4k_xg_no_limit_control
        PROPERTIES TIMEOUT 30 ENVIRONMENT "X2W_D3D12_PERMISSIVE=1")
    set_tests_properties(startup_small_texture_4k_xg_no_limit_control PROPERTIES WILL_FAIL TRUE)
    # gfx2hlsl v_mul_hi_u32 (#870): CPU helper evaluation, refusal and mutation controls, then desktop draw (FXC 5_1 and DXC 6_0).
    add_test(NAME startup_gfx2hlsl_mul_hi_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul_hi_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_mul_hi_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_mul_hi_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_mul_hi_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_sad_u8, v_sad_u16 and v_sad_u32: on-demand helpers, CPU grid evaluation, refusal and mutation controls, then desktop draw (FXC 5_1 and DXC 6_0).
    add_test(NAME startup_gfx2hlsl_sad_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sad_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_sad_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sad_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_sad_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl v_sad_hi_u8 (0x15b) and v_msad_u8 (0x171): the shared sad4_u8 helper, value evaluation against the
    # tools/pixel_aot.py formulas (zero-src1-byte and 2^32 carry cases), refusals and the unchanged v_sad_u8 output.
    add_test(NAME startup_gfx2hlsl_sad_hi_msad_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_sad_hi_msad_check.py")
    add_test(NAME startup_xg_bc_tiling COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_xg_bc_tiling_check.py" "$<TARGET_FILE:startup_stub_xg_xs>")
    set_tests_properties(startup_xg_bc_tiling PROPERTIES TIMEOUT 30 ENVIRONMENT "X2W_D3D12_PERMISSIVE=1")
    add_test(NAME startup_xg_tile64_tiling COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_xg_tile64_tiling_check.py" "$<TARGET_FILE:startup_stub_xg_xs>")
    set_tests_properties(startup_xg_tile64_tiling PROPERTIES TIMEOUT 30 ENVIRONMENT "X2W_D3D12_PERMISSIVE=1")
    add_test(NAME startup_inline_sampler_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_inline_sampler_check.py")
    add_test(NAME startup_gfx2hlsl_root COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_root_check.py")
    set_tests_properties(startup_gfx2hlsl_root PROPERTIES TIMEOUT 60)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_inline_sampler_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_inline_sampler_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_inline_sampler_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    # gfx2hlsl binary32 reciprocal, roots, exp2 and log2 (VEC_F) on exact inputs: translation controls, then a
    # draw of the translated pairs with reference words and one mutated lowering per operation.
    add_test(NAME startup_gfx2hlsl_float_transcendental_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_float_transcendental_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_float_transcendental_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_float_transcendental_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_float_transcendental_${adapter} PROPERTIES TIMEOUT 300
            SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME startup_gfx2hlsl_scalar_shift64_bfe_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_shift64_bfe_check.py")
    add_test(NAME startup_gfx2hlsl_scalar_m0_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_m0_check.py" controls)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_scalar_m0_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_scalar_m0_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_scalar_m0_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME startup_xg_bc7_layout COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_xg_bc7_layout_check.py" "$<TARGET_FILE:startup_stub_xg_xs>")
    set_tests_properties(startup_xg_bc7_layout PROPERTIES TIMEOUT 30
        ENVIRONMENT "X2W_D3D12_PERMISSIVE=1;X2W_XG_BC7_4K_S_LAYOUT=1")
    # tools/startup/launch.py's containment (#1149): the exit code, captured stdout/stderr and trap
    # log, the timeout kill, the commit cap and the process limit, and the missing-EXE path.
    add_test(NAME startup_launch COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_launch_check.py" "$<TARGET_FILE:startup_launch_probe>")
    set_tests_properties(startup_launch PROPERTIES TIMEOUT 120)
    add_test(NAME startup_launch_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_launch_cli_check.py")
    set_tests_properties(startup_launch_cli_check PROPERTIES TIMEOUT 30)
    find_program(STARTUP_POWERSHELL NAMES powershell pwsh REQUIRED)
    add_test(NAME startup_stage_package COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stage_package_check.py" "${STARTUP_POWERSHELL}")
    set_tests_properties(startup_stage_package PROPERTIES TIMEOUT 120)
    # One script, three groups of cases that ctest can run in parallel. startup_debug keeps the old
    # name; select all three with -R '^startup_debug' (the anchored -R '^startup_debug$' runs only the core group).
    foreach(group IN ITEMS core log hooks)
        if(group STREQUAL "core")
            set(startup_debug_test startup_debug)
        else()
            set(startup_debug_test startup_debug_${group})
        endif()
        add_test(NAME ${startup_debug_test} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_debug_check.py" "$<TARGET_FILE:startup_debug_probe>"
            "$<TARGET_FILE:startup_debug_calls>" ${group})
        set_tests_properties(${startup_debug_test} PROPERTIES TIMEOUT 300)
    endforeach()

    add_test(NAME startup_stream_request_warp COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
        "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_check.py" "$<TARGET_FILE:startup_stream_consumer>")
    # Device slot 67 compute pipelines publish req_<key>.{desc,sa,sb,data,root,c67}; the control (render mode off) must fail.
    add_test(NAME startup_compute_binding_trace_warp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_binding_trace_check.py"
        "$<TARGET_FILE:startup_compute_binding_trace>")
    set_tests_properties(startup_compute_binding_trace_warp PROPERTIES TIMEOUT 30)
    add_test(NAME startup_compute_request_warp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_request_check.py" "$<TARGET_FILE:startup_stream_consumer>")
    add_test(NAME startup_compute_request_disabled_control COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_request_check.py" "$<TARGET_FILE:startup_stream_consumer>" disabled)
    set_tests_properties(startup_compute_request_warp startup_compute_request_disabled_control PROPERTIES TIMEOUT 60)
    set_tests_properties(startup_compute_request_disabled_control PROPERTIES PASS_REGULAR_EXPRESSION "FAIL: no compute request")
    # Slot 67 request translation: request checks, then stand-in request -> --pending -> DXC -> dispatch; the
    # wrong-group control must mismatch.
    add_test(NAME startup_compute_translate_requests COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_translate_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_compute_translate_e2e_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_translate_check.py" e2e "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" "$<TARGET_FILE:offscreen_check>" ${adapter})
        add_test(NAME startup_compute_translate_e2e_wrong_group_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_translate_check.py" e2e "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" "$<TARGET_FILE:offscreen_check>" ${adapter} wrong-group)
        set_tests_properties(startup_compute_translate_e2e_${adapter} startup_compute_translate_e2e_wrong_group_${adapter}
            PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        set_tests_properties(startup_compute_translate_e2e_wrong_group_${adapter} PROPERTIES
            PASS_REGULAR_EXPRESSION "control wrong-group: rejected at word=[0-9]+ ")
        add_test(NAME startup_compute_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_dispatch_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        add_test(NAME startup_compute_dispatch_texture_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_dispatch_texture_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        add_test(NAME startup_slot67_indirect_dispatch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_slot67_indirect_dispatch_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        set_tests_properties(startup_slot67_indirect_dispatch_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_compute_dispatch_heap_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_dispatch_heap_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        add_test(NAME startup_compute_dispatch_heap_word_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_dispatch_heap_word_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        add_test(NAME startup_compute_dispatch_input_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_dispatch_input_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        add_test(NAME startup_compute_live_retry_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_live_retry_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        add_test(NAME startup_compute_dispatch_entry_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_dispatch_entry_check.py" "$<TARGET_FILE:startup_stream_consumer>"
            "${DXC_EXECUTABLE}" ${adapter})
        set_tests_properties(startup_compute_dispatch_${adapter} startup_compute_dispatch_texture_${adapter}
            startup_compute_dispatch_heap_${adapter} startup_compute_dispatch_heap_word_${adapter}
            startup_compute_live_retry_${adapter} startup_compute_dispatch_entry_${adapter}
            startup_compute_dispatch_input_${adapter}
            PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    add_test(NAME startup_stream_adapter_filter COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_rasterizer_check.py"
        "$<TARGET_FILE:startup_stream_rasterizer>" hardware filter)
    set_tests_properties(startup_stream_adapter_filter PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
    add_test(NAME startup_indirect_dispatch_adapter_filter COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/hardware_adapter_filter_check.py"
        "$<TARGET_FILE:startup_indirect_dispatch>" hardware count)
    set_tests_properties(startup_indirect_dispatch_adapter_filter PROPERTIES TIMEOUT 30)
    foreach(backend IN ITEMS warp hardware)
        add_test(NAME startup_stream_draw_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_draw_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_stream_draw_${backend} PROPERTIES TIMEOUT 90)
        add_test(NAME startup_stream_viewport_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_viewport_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_stream_viewport_${backend} PROPERTIES TIMEOUT 90)
        add_test(NAME startup_stream_fetch_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_fetch_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_stream_fetch_${backend} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_stream_interface_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_interface_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_stream_interface_${backend} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_stream_depth_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_depth_check.py"
            "$<TARGET_FILE:startup_stream_depth>" "${backend}")
        set_tests_properties(startup_stream_depth_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_stream_rasterizer_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_rasterizer_check.py"
            "$<TARGET_FILE:startup_stream_rasterizer>" "${backend}")
        set_tests_properties(startup_stream_rasterizer_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_stream_rasterizer_ignore_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_rasterizer_check.py"
            "$<TARGET_FILE:startup_stream_rasterizer>" "${backend}" ignore)
        set_tests_properties(startup_stream_rasterizer_ignore_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77 WILL_FAIL TRUE)
        add_test(NAME startup_slot57_depth_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_slot57_depth_check.py"
            "$<TARGET_FILE:startup_slot57_depth>" "${backend}")
        set_tests_properties(startup_slot57_depth_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        # The drop control draws the bound case with the depth binding dropped (a zero handle) and passes only when
        # it reads back that unbound picture; the debug test reports a skip (77) without a debug layer.
        add_test(NAME startup_draw_depth_target_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_draw_depth_target_check.py"
            "$<TARGET_FILE:startup_draw_depth_target>" "${backend}" check)
        add_test(NAME startup_draw_depth_target_drop_control_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_draw_depth_target_check.py"
            "$<TARGET_FILE:startup_draw_depth_target>" "${backend}" drop)
        add_test(NAME startup_draw_depth_target_debug_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_draw_depth_target_check.py"
            "$<TARGET_FILE:startup_draw_depth_target>" "${backend}" debug)
        set_tests_properties(startup_draw_depth_target_${backend} startup_draw_depth_target_drop_control_${backend}
            startup_draw_depth_target_debug_${backend} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(compiler IN ITEMS fxc dxc)
            add_test(NAME startup_joined_table_pointer_${compiler}_${backend} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_joined_table_pointer_check.py"
                "$<TARGET_FILE:startup_stream_consumer>" "${backend}" "${compiler}" "${DXC_EXECUTABLE}" "${STARTUP_FXC}")
            set_tests_properties(startup_joined_table_pointer_${compiler}_${backend} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
            add_test(NAME startup_mrt_${compiler}_${backend} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mrt_check.py"
                "$<TARGET_FILE:startup_stream_consumer>" "${backend}" "${compiler}" "${DXC_EXECUTABLE}" "${STARTUP_FXC}")
            set_tests_properties(startup_mrt_${compiler}_${backend} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        endforeach()
        add_test(NAME startup_logical_view_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_logical_view_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_logical_view_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_xg_bc7_draw_${backend} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_xg_bc7_draw_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${DXC_EXECUTABLE}" "${backend}")
        set_tests_properties(startup_xg_bc7_draw_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        # A two-mip texture given the 4 KiB allocation answer: XG slot 8 into exactly the reported size before a
        # guard page, placed, drawn and read back pixel for pixel (src/startup_stubs/small_texture_4k.h).
        add_test(NAME startup_small_texture_4k_draw_${backend} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_small_texture_4k_draw_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${DXC_EXECUTABLE}" "${backend}")
        set_tests_properties(startup_small_texture_4k_draw_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_slot57_blend_draw_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_slot57_blend_draw_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_slot57_blend_draw_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_indirect_requests_${backend} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_indirect_requests_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_indirect_requests_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_formatted_view_draw_${backend} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_formatted_view_draw_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}" "${STARTUP_FXC}")
        set_tests_properties(startup_formatted_view_draw_${backend} PROPERTIES TIMEOUT 240 SKIP_RETURN_CODE 77)
        add_test(NAME startup_packed_target_draw_${backend} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_packed_target_draw_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${DXC_EXECUTABLE}" "${backend}")
        set_tests_properties(startup_packed_target_draw_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_1d_srv_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_1d_srv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" ${backend})
        set_tests_properties(startup_1d_srv_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_root_reset_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_root_reset_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" ${backend})
        set_tests_properties(startup_root_reset_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_root_cbv_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_root_cbv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" ${backend})
        set_tests_properties(startup_root_cbv_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_root_heap_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_root_heap_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" ${backend})
        set_tests_properties(startup_root_heap_${backend} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_address_srv_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_srv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_address_srv_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        if(backend STREQUAL "warp")
            # Negative control for X2W_RESOURCE_INDEX_CHECK: mode 2 skips the index inserts, so the check must
            # report the first live resource it does not find (the run passes only on that report).
            add_test(NAME startup_resource_address_index_missing_control_warp COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
                "X2W_RESOURCE_INDEX_CHECK=2" "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_srv_check.py"
                "$<TARGET_FILE:startup_stream_consumer>" warp)
            set_tests_properties(startup_resource_address_index_missing_control_warp PROPERTIES TIMEOUT 90
                PASS_REGULAR_EXPRESSION "resource address index misses a live resource")
        endif()
        # Refused slot 70 calls and "token" texture nulls in the five-second report census. The WARP control
        # publishes a supported R8 texture in place of the refused one and passes only on the exact mismatch
        # that causes (column 0 samples the R8 texel instead of a null view).
        add_test(NAME startup_memory_srv_diag_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_memory_srv_diag_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_memory_srv_diag_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        if(backend STREQUAL "warp")
            add_test(NAME startup_memory_srv_diag_supported_control_warp COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
                "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_memory_srv_diag_check.py"
                "$<TARGET_FILE:startup_stream_consumer>" warp --control)
            set_tests_properties(startup_memory_srv_diag_supported_control_warp PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        endif()
        add_test(NAME startup_address_single_element_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_single_element_srv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_address_single_element_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_address_buffer_srv_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_buffer_srv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_address_buffer_srv_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_copied_vertex_srv_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_copied_vertex_srv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_copied_vertex_srv_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_direct_index_late_write_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_direct_index_late_write_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_direct_index_late_write_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_mubuf_descriptor_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_mubuf_descriptor_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_mubuf_descriptor_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_address_volume_srv_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_volume_srv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_address_volume_srv_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_d16_srv_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_d16_srv_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_d16_srv_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        # A translated pixel-stage image store bound from the title's table (#1996 item F): the stored texel and
        # every other word of four textures read back, each refusal by its reason, and the exec controls.
        add_test(NAME startup_pixel_uav_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_pixel_uav_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_pixel_uav_${backend} PROPERTIES TIMEOUT 240 SKIP_RETURN_CODE 77)
        add_test(NAME startup_frame_copy_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_frame_copy_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" ${backend})
        set_tests_properties(startup_frame_copy_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_placed_vertex_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_placed_vertex_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_placed_vertex_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_address_bc_view_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_bc_view_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_address_bc_view_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_address_console_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_console_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_address_console_${backend} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77)
        # Uploads of by-address textures recorded while the queue waits on a fence keep their bytes until the
        # queue has run them. The ring control fills them from the shared upload ring and must lose the first.
        # gate-ring-reuse: once those submits have completed, the ring must accept new uploads again.
        foreach(gate IN ITEMS gate gate-ring gate-ring-reuse)
            string(REPLACE "-" "_" gate_name "${gate}")
            add_test(NAME startup_address_console_${gate_name}_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
                "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_console_check.py"
                "$<TARGET_FILE:startup_stream_consumer>" "${backend}" "${gate}")
            set_tests_properties(startup_address_console_${gate_name}_${backend} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
        endforeach()
        # gate-ring-untracked: the same gate with X2W_TEST_SUBMIT_FENCE_FAIL=1, so no chunk the ring served
        # can be tied to a fence value. Once every submit has run and the recording is discarded (recordings
        # back to 0), one more full-size payload must still be refused: an untracked chunk is never recycled.
        add_test(NAME startup_address_console_gate_ring_untracked_${backend} COMMAND "${CMAKE_COMMAND}" -E env
            "X2W_FXC=${STARTUP_FXC}" "X2W_TEST_SUBMIT_FENCE_FAIL=1"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_address_console_check.py"
            "$<TARGET_FILE:startup_stream_consumer>" "${backend}" "gate-ring-untracked")
        set_tests_properties(startup_address_console_gate_ring_untracked_${backend} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
        add_test(NAME startup_xg_bc_chain_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_xg_bc_chain_check.py"
            "$<TARGET_FILE:startup_stub_xg_xs>" "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_xg_bc_chain_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_xg_bc_array_${backend} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_xg_bc_array_check.py"
            "$<TARGET_FILE:startup_stub_xg_xs>" "$<TARGET_FILE:startup_stream_consumer>" "${backend}")
        set_tests_properties(startup_xg_bc_array_${backend} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
    endforeach()
    set_tests_properties(startup_stream_draw_hardware startup_stream_viewport_hardware PROPERTIES SKIP_RETURN_CODE 77)
    set_tests_properties(startup_stream_request_warp PROPERTIES TIMEOUT 60)

    # Stream vertex fetch from the input layout: the translator-only cases (draws: startup_stream_fetch_<backend>).
    add_test(NAME startup_stream_fetch_translate COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_fetch_check.py")
    # Stream stage interface by semantic: the translator-only cases (draws: startup_stream_interface_<backend>).
    add_test(NAME startup_stream_interface_translate COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_stream_interface_check.py")
    # Startup shader translator: descriptor offsets inside wide scalar loads (no game data).
    add_test(NAME startup_translator COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_translator_check.py")
    # Startup shader translator: the SMEM offset 'off' is the literal 0; m0 and other operands keep their handling (#1674).
    add_test(NAME startup_gfx2hlsl_smem_offset COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_smem_offset_check.py")
    # gfx2hlsl binary32 arithmetic (VEC_F): translation controls, then a draw of the translated pairs with exact
    # reference words and one mutated lowering per operation.
    add_test(NAME startup_gfx2hlsl_float_alu_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_float_alu_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_float_alu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_gfx2hlsl_float_alu_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_gfx2hlsl_float_alu_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # Startup shader translator: s_load descriptor into s[104:107] (vcc is s106/s107) (#1723).
    add_test(NAME startup_gfx2hlsl_sload_s104 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sload_s104_check.py")
    add_test(NAME startup_gfx2hlsl_desc_vcc COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_desc_vcc_check.py")
    # Startup shader translator: scalar constants are dropped at a branch join that another path writes (loop counters).
    add_test(NAME startup_gfx2hlsl_loop_constants COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_loop_constants_check.py")
    # Startup shader translator: symbols that are not constants (descriptors, pointers, pairs) at a branch join.
    add_test(NAME startup_gfx2hlsl_join_symbols_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_join_symbols_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME startup_gfx2hlsl_join_symbols_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_join_symbols_check.py" dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        add_test(NAME startup_gfx2hlsl_join_symbols_folded_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_join_symbols_check.py" control "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_gfx2hlsl_join_symbols_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        set_tests_properties(startup_gfx2hlsl_join_symbols_folded_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            PASS_REGULAR_EXPRESSION "control OUTSIDE: 3 in all four channels")
    endforeach()
    # Startup shader translator: s_load with a register offset holding a known constant reaches the heap descriptor (#1723).
    add_test(NAME startup_gfx2hlsl_sload_const_offset COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_sload_const_offset_check.py")
    # Startup shader translator: uniform sources of v_readfirstlane_b32 in straight-line code and entry blocks (#1723).
    add_test(NAME startup_gfx2hlsl_readfirstlane_uniform COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_readfirstlane_uniform_check.py")
    # v_readfirstlane_b32 past the entry block of a branched program: recomputed definition, joins and EXEC refused.
    add_test(NAME startup_gfx2hlsl_readfirstlane_recompute COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_readfirstlane_recompute_check.py")
    # A uniform compute buffer load past the entry block: per-lane temporary, joins, EXEC and per-lane addresses refused.
    add_test(NAME startup_gfx2hlsl_readfirstlane_load_recompute COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_readfirstlane_load_recompute_check.py")
    add_test(NAME startup_gfx2hlsl_calculated_target COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_calculated_target_check.py")
    # Startup shader translator: read-only census of every refusal site (--refusals).
    add_test(NAME startup_gfx2hlsl_refusals COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_refusals_check.py")
    # Device slot 67 compute requests offline: key vector, --pending and --refusals (pure Python).
    add_test(NAME startup_compute_request_offline COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_compute_request_offline_check.py")
    add_test(NAME compute_container_index COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/compute_container_index_check.py")
    add_test(NAME compute_container_index_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/compute_container_index_cli_check.py")
    # Offline re-key of saved shader requests under the current cache revision (pure Python).
    add_test(NAME startup_shader_cache_rekey COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_shader_cache_rekey_check.py")
    add_test(NAME runtime_shader_cache_rekey_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_shader_cache_rekey_cli_check.py")
    # Partial colour exports carry their channel mask to the manifest; compressed exports of whole pairs lower (#1674).
    add_test(NAME startup_gfx2hlsl_export_mask COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_export_mask_check.py")
    add_test(NAME startup_gfx2hlsl_export_mask_drop_control COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_gfx2hlsl_export_mask_check.py" --mutate drop-mask)
    set_tests_properties(startup_gfx2hlsl_export_mask_drop_control PROPERTIES WILL_FAIL TRUE)
    add_test(NAME startup_triage_run COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_triage_run_check.py")
    add_test(NAME runtime_startup_triage_run_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_triage_run_cli_check.py")
    set_tests_properties(runtime_startup_triage_run_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME startup_run_ps1 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_run_ps1_check.py")
    # The Linux launcher's check exits 77 on Windows; the Ubuntu job runs it.
    add_test(NAME startup_run_sh COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/startup_run_sh_check.py")
    set_tests_properties(startup_run_sh PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME xmem_shim_mapped_pages COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_mapped_pages_check.py" "$<TARGET_FILE:xmem_shim>")
    # Large batches: pages as slots of shared sections, adjacent pages in one view.
    add_test(NAME xmem_shim_page_runs COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_page_runs_check.py" "$<TARGET_FILE:xmem_shim>"
        "$<TARGET_FILE:xmem_shim_test_controls>")
    set_tests_properties(xmem_shim_page_runs PROPERTIES TIMEOUT 300)
    add_test(NAME docs_links COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/docs_links_check.py")
    add_test(NAME emit_variants COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/emit_variants_check.py")
    add_test(NAME emit_variants_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/emit_variants_cli_check.py")
    add_test(NAME coverage_svg COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/coverage_svg_check.py")
    add_test(NAME ci_coverage_svg_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/coverage_svg_cli_check.py")
    set_tests_properties(ci_coverage_svg_cli_check PROPERTIES TIMEOUT 60)
    # Compile-only: outcome classification and GVN pass shares, no wall-time threshold (#775).
    add_test(NAME dxc_compile_time_gvn COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/dxc_compile_time_check.py" "${DXC_EXECUTABLE}")
    set_tests_properties(dxc_compile_time_gvn PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    add_test(NAME dxc_compile_time_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/dxc_compile_time_cli_check.py")
    set_tests_properties(dxc_compile_time_cli_check PROPERTIES TIMEOUT 60)
    # Dispatch condstore_256 built with and without GVN; compare the whole raw UAV bit for bit (#775).
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME dxc_gvn_output_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/dxc_gvn_output_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(dxc_gvn_output_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77)
    endforeach()
    # tools/setup-spirv-tools.ps1 builds the pinned tools into out/tools/spirv/bin.
    set(spirv_tool_hints "${CMAKE_SOURCE_DIR}/out/tools/spirv/bin" "$ENV{VULKAN_SDK}/Bin")
    find_program(SPIRV_WINDOW_AS spirv-as HINTS ${spirv_tool_hints})
    find_program(SPIRV_WINDOW_VAL spirv-val HINTS ${spirv_tool_hints})
    find_program(SPIRV_WINDOW_CROSS spirv-cross HINTS ${spirv_tool_hints})
    # Registered unconditionally: without the tools the wrapper reports a skip (77) rather than the
    # tests silently disappearing. Hosted CI sets X2W_REQUIRE_SPIRV_TOOLS=1 to turn skips into failures.
    foreach(adapter IN ITEMS hardware warp)
        foreach(bridge IN ITEMS address_window:draw address_window_atomic:atomic address_window_signed:address_signed
                                address_window_float:address_float address_window_vec4:address_vec4
                                address_window_qword:qword
                                sampler_views:sampler ballot_extract:ballot
                                compaction:compaction compare_sampler:compare_sampler minlod:minlod
                                minlod_exact:minlod_exact minlod_levels:minlod_levels
                                minlod_fractional:minlod_fractional)
            string(REPLACE ":" ";" bridge "${bridge}")
            list(GET bridge 0 name)
            list(GET bridge 1 driver)
            add_test(NAME spirv_${name}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/spirv_window/run_bridge_test.py"
                "${CMAKE_SOURCE_DIR}/tests/spirv_window/${driver}.py" "${SPIRV_WINDOW_AS}" "${SPIRV_WINDOW_VAL}"
                "${SPIRV_WINDOW_CROSS}" "${DXC_EXECUTABLE}" "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(spirv_${name}_${adapter} PROPERTIES SKIP_RETURN_CODE 77)
        endforeach()
    endforeach()
    add_test(NAME spirv_window_checks COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/spirv_sampler_split_check.py")
    add_test(NAME shader_spirv_ballot_extract_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/spirv_ballot_extract_check.py")
    set_tests_properties(shader_spirv_ballot_extract_check PROPERTIES TIMEOUT 60)
    add_test(NAME spirv_address_window_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/spirv_address_window_check.py")
    add_test(NAME shader_spirv_address_window_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/spirv_address_window_cli_check.py")
    set_tests_properties(shader_spirv_address_window_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME shader_section_probe_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/section_probe_cli_check.py")
    # Outside a Git checkout, such as a source archive, the tracked-path check cannot run.
    set_tests_properties(docs_links PROPERTIES SKIP_RETURN_CODE 77)

    enable_language(ASM_MASM)
    function(cpu_asm_fixture image source)
        if(ARGC GREATER 2)
            set(exports "${ARGV2}")
        else()
            set(exports "${source}")
        endif()
        add_library(${image} SHARED tests/cpu/${source}.asm tests/cpu/${exports}.def)
        set_target_properties(${image} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(${image} PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO)
    endfunction()
    # One Python process writes every variant of a fixture (tests/cpu/<script>.py emit), so the interpreter
    # and the lifter modules load once per fixture instead of once per variant. Each variant is written to
    # ${CMAKE_CURRENT_BINARY_DIR}/<image>_<variant>.cpp, as the per-variant commands wrote it.
    function(x2w_emit_variants script image variants)
        set(outputs)
        set(pairs)
        foreach(variant IN LISTS variants)
            set(output "${CMAKE_CURRENT_BINARY_DIR}/${image}_${variant}.cpp")
            list(APPEND outputs "${output}")
            list(APPEND pairs "${variant}=${output}")
        endforeach()
        add_custom_command(OUTPUT ${outputs}
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/emit_variants.py"
                "${CMAKE_SOURCE_DIR}/tests/cpu/${script}.py" "$<TARGET_FILE:${image}>" ${pairs}
            DEPENDS ${image} tests/cpu/${script}.py tools/emit_variants.py ${ARGN} VERBATIM)
    endfunction()
    # A long check is split into parallel CTest cases <test>_<part>. The original <test> keeps its name (the
    # form-coverage source header and the docs name it), runs the cheap remainder, and requires every part
    # through a CTest fixture, so it is "not run" (not covered) unless every part passed.
    function(x2w_add_check_part test part)
        add_test(NAME ${test}_${part} COMMAND ${ARGN})
        set_tests_properties(${test}_${part} PROPERTIES FIXTURES_SETUP ${test}_${part})
    endfunction()
    function(x2w_require_check_parts test)
        set(required)
        foreach(part IN LISTS ARGN)
            list(APPEND required ${test}_${part})
        endforeach()
        set_tests_properties(${test} PROPERTIES FIXTURES_REQUIRED "${required}")
    endfunction()
    function(cpu_translation image translator entry)
        cmake_parse_arguments(BIND "FFX_DESTROY;IMAGE_DATA;HOST_CPU"
            "PROVIDER;SYMBOL;LINK_NAME;CALLBACK_OFFSET;IMPORT_ARGUMENTS;RETURN_BYTES;NAME;RANGES;SECOND_PROVIDER;SECOND_SYMBOL;SECOND_LINK_NAME;SECOND_IMPORT_ARGUMENTS;SECOND_RETURN_BYTES" "STACK_OUTPUT" ${ARGN})
        if(NOT BIND_NAME)
            set(BIND_NAME ${image}_lifted)
        endif()
        set(binding)
        if(BIND_FFX_DESTROY)
            list(APPEND binding --ffx-destroy)
        endif()
        if(BIND_RANGES)
            list(APPEND binding --bind-ranges "${BIND_RANGES}")
        endif()
        if(DEFINED BIND_CALLBACK_OFFSET)
            list(APPEND binding --callback-offset "${BIND_CALLBACK_OFFSET}")
        endif()
        if(BIND_PROVIDER)
            set(binding --bind "$<TARGET_FILE:${BIND_PROVIDER}>" "${BIND_SYMBOL}")
            if(BIND_LINK_NAME)
                list(APPEND binding --link-name "${BIND_LINK_NAME}")
            endif()
            if(DEFINED BIND_IMPORT_ARGUMENTS)
                list(APPEND binding --import-arguments "${BIND_IMPORT_ARGUMENTS}" --return-bytes "${BIND_RETURN_BYTES}")
            endif()
            if(BIND_STACK_OUTPUT)
                list(APPEND binding --stack-output ${BIND_STACK_OUTPUT})
            endif()
        endif()
        # A second ordinary import binding, given as its own --bind group after the first.
        if(BIND_SECOND_PROVIDER)
            list(APPEND binding --bind "$<TARGET_FILE:${BIND_SECOND_PROVIDER}>" "${BIND_SECOND_SYMBOL}")
            if(BIND_SECOND_LINK_NAME)
                list(APPEND binding --link-name "${BIND_SECOND_LINK_NAME}")
            endif()
            list(APPEND binding --import-arguments "${BIND_SECOND_IMPORT_ARGUMENTS}"
                --return-bytes "${BIND_SECOND_RETURN_BYTES}")
        endif()
        if(BIND_IMAGE_DATA)
            list(APPEND binding --image-data)
        endif()
        if(BIND_HOST_CPU)
            list(APPEND binding --host-cpu)
        endif()
        set(lifted "${CMAKE_CURRENT_BINARY_DIR}/${BIND_NAME}.cpp")
        add_custom_command(OUTPUT "${lifted}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/${translator}.py"
                "$<TARGET_FILE:${image}>" ${entry} "${lifted}" ${binding}
            DEPENDS ${image} ${BIND_PROVIDER} ${BIND_SECOND_PROVIDER} ${BIND_RANGES} tools/${translator}.py
                tools/cpu_leaf_aot.py tools/cpu_ranges.py tools/cpu_call_aot.py VERBATIM)
        add_library(${BIND_NAME} SHARED "${lifted}")
        if(BIND_PROVIDER)
            target_link_libraries(${BIND_NAME} PRIVATE ${BIND_PROVIDER})
        endif()
        if(BIND_SECOND_PROVIDER)
            target_link_libraries(${BIND_NAME} PRIVATE ${BIND_SECOND_PROVIDER})
        endif()
    endfunction()
    cpu_asm_fixture(cpu_clzero counted_clzero)
    cpu_translation(cpu_clzero cpu_switch_aot counted,loop_dx,loop_r8,loop_r9,loop_r10)
    add_test(NAME cpu_counted_clzero COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/counted_clzero.py" "$<TARGET_FILE:cpu_clzero>" "$<TARGET_FILE:cpu_clzero_lifted>"
        "${CMAKE_SOURCE_DIR}/tools/cpu_switch_aot.py" "${CMAKE_CURRENT_BINARY_DIR}")
    set_tests_properties(cpu_counted_clzero PROPERTIES
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_counted_clzero.txt")

    foreach(variant IN ITEMS original inverted)
        cpu_asm_fixture(cpu_leaf_${variant} branch)
        cpu_translation(cpu_leaf_${variant} cpu_leaf_aot branch_value)
    endforeach()
    target_compile_definitions(cpu_leaf_inverted PRIVATE INVERT_BRANCH)
    add_test(NAME cpu_leaf_aot_branches COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/branches.py" "$<TARGET_FILE:cpu_leaf_original>"
        "$<TARGET_FILE:cpu_leaf_original_lifted>" "$<TARGET_FILE:cpu_leaf_inverted_lifted>")
    add_test(NAME cpu_aot_malformed_pe COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/malformed_pe_check.py")
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_call_${variant} direct)
        cpu_translation(cpu_call_${variant} cpu_call_aot call_mix)
        # Keep the linked caller's rel32 directed at the callee itself for inspection.
        target_link_options(cpu_call_${variant}_lifted PRIVATE /INCREMENTAL:NO)
    endforeach()
    target_compile_definitions(cpu_call_altered PRIVATE ALTER_RETURN)
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_repeat_${variant} repeat_call)
        cpu_translation(cpu_repeat_${variant} cpu_call_aot call_twice)
        target_link_options(cpu_repeat_${variant}_lifted PRIVATE /INCREMENTAL:NO)
    endforeach()
    target_compile_definitions(cpu_repeat_altered PRIVATE ALTER_RETURN)
    # Translation must reject this copy, which omits the trace-pointer reload.
    cpu_asm_fixture(cpu_repeat_dropped repeat_call)
    target_compile_definitions(cpu_repeat_dropped PRIVATE DROP_RELOAD)
    foreach(variant IN ITEMS original swapped first second)
        cpu_asm_fixture(cpu_pair_${variant} call_pair)
        cpu_translation(cpu_pair_${variant} cpu_call_aot call_pair)
        target_link_options(cpu_pair_${variant}_lifted PRIVATE /INCREMENTAL:NO)
    endforeach()
    target_compile_definitions(cpu_pair_swapped PRIVATE SWAP_CALLS)
    target_compile_definitions(cpu_pair_first PRIVATE ALTER_FIRST)
    target_compile_definitions(cpu_pair_second PRIVATE ALTER_SECOND)
    cpu_asm_fixture(cpu_register_probe register_probe)
    foreach(variant IN ITEMS original swapped)
        cpu_asm_fixture(cpu_switch_${variant} switch)
        cpu_translation(cpu_switch_${variant} cpu_switch_aot select_rva,select_rel,run_ops,shift_narrow,flag_select,cmov_read,select_rel_edges)
    endforeach()
    target_compile_definitions(cpu_switch_swapped PRIVATE SWAP_TABLE)
    foreach(variant IN ITEMS original swapped)
        cpu_asm_fixture(cpu_switch_inverted_${variant} switch_inverted)
        cpu_translation(cpu_switch_inverted_${variant} cpu_switch_aot inv_rva_jbe,inv_rel_jb,inv_rel_window_jbe)
    endforeach()
    target_compile_definitions(cpu_switch_inverted_swapped PRIVATE SWAP_TABLE)
    add_test(NAME cpu_aot_switch_inverted COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_inverted_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_inverted_original>" "$<TARGET_FILE:cpu_switch_inverted_original_lifted>"
        "$<TARGET_FILE:cpu_switch_inverted_swapped_lifted>")
    add_test(NAME cpu_aot_jump_tables COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_original>" "$<TARGET_FILE:cpu_switch_original_lifted>"
        "$<TARGET_FILE:cpu_switch_swapped_lifted>")
    cpu_asm_fixture(cpu_flag_conditions flag_conditions)
    set(flag_conditions_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_flag_conditions_lifted.cpp")
    add_custom_command(OUTPUT "${flag_conditions_lifted}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/flag_conditions_check.py"
            emit "$<TARGET_FILE:cpu_flag_conditions>" "${flag_conditions_lifted}"
        DEPENDS cpu_flag_conditions tests/cpu/flag_conditions_check.py tools/cpu_switch_aot.py
            tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
    add_library(cpu_flag_conditions_lifted SHARED "${flag_conditions_lifted}")
    add_test(NAME cpu_aot_flag_conditions COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/flag_conditions_check.py" check
        "$<TARGET_FILE:cpu_flag_conditions>" "$<TARGET_FILE:cpu_flag_conditions_lifted>")
    set_tests_properties(cpu_aot_flag_conditions PROPERTIES
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_flag_conditions.txt")
    set(CPU_FUZZ_SEED "0xA902" CACHE STRING "Seed for the CPU differential fuzz smoke test")
    set(CPU_FUZZ_FUNCTIONS "20" CACHE STRING "Number of generated functions in the CPU differential fuzz smoke test")
    set(cpu_fuzz_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz.asm")
    set(cpu_fuzz_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz.def")
    add_custom_command(OUTPUT "${cpu_fuzz_asm}" "${cpu_fuzz_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_SEED}" "${CPU_FUZZ_FUNCTIONS}" "${cpu_fuzz_asm}" "${cpu_fuzz_def}"
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz SHARED "${cpu_fuzz_asm}" "${cpu_fuzz_def}")
    set_target_properties(cpu_fuzz PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_lifted.cpp")
    add_custom_command(OUTPUT "${cpu_fuzz_lifted}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
            "${CPU_FUZZ_SEED}" "${CPU_FUZZ_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz>" "${cpu_fuzz_lifted}"
        DEPENDS cpu_fuzz tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
            tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
    add_library(cpu_fuzz_lifted SHARED "${cpu_fuzz_lifted}")
    target_compile_features(cpu_fuzz_lifted PRIVATE cxx_std_20)
    set(cpu_fuzz_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_lifted_o2.obj" "/Fe${cpu_fuzz_o2}"
        DEPENDS "${cpu_fuzz_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_lifted_o2 ALL DEPENDS "${cpu_fuzz_o2}")
    add_test(NAME cpu_aot_fuzz_smoke COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_SEED}" "${CPU_FUZZ_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz>" "$<TARGET_FILE:cpu_fuzz_lifted>" "${cpu_fuzz_o2}")
    set_tests_properties(cpu_aot_fuzz_smoke PROPERTIES TIMEOUT 60)
    add_test(NAME tooling_fuzz_cpu_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/fuzz_cpu_cli_check.py")
    set_tests_properties(tooling_fuzz_cpu_cli_check PROPERTIES TIMEOUT 60)
    # Fixed RSP frames: saved nonvolatile registers, partial spill overlaps and a planted reload fault.
    set(CPU_FUZZ_FRAMES_SEED "0xF4A3" CACHE STRING "Seed for the CPU differential fuzz frame test")
    set(CPU_FUZZ_FRAMES_FUNCTIONS "16" CACHE STRING "Number of generated functions in the CPU differential fuzz frame test")
    set(cpu_fuzz_frames_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_frames.asm")
    set(cpu_fuzz_frames_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_frames.def")
    add_custom_command(OUTPUT "${cpu_fuzz_frames_asm}" "${cpu_fuzz_frames_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_FRAMES_SEED}" "${CPU_FUZZ_FRAMES_FUNCTIONS}" "${cpu_fuzz_frames_asm}"
            "${cpu_fuzz_frames_def}" --area frames
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_frames SHARED "${cpu_fuzz_frames_asm}" "${cpu_fuzz_frames_def}")
    set_target_properties(cpu_fuzz_frames PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_frames PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_frames_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_frames_lifted.cpp")
    set(cpu_fuzz_frames_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_frames_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_frames_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_FRAMES_SEED}" "${CPU_FUZZ_FRAMES_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_frames>"
                "${cpu_fuzz_frames_${variant}}" --area frames ${mutant_flag}
            DEPENDS cpu_fuzz_frames tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_frames_${variant} SHARED "${cpu_fuzz_frames_${variant}}")
        target_compile_features(cpu_fuzz_frames_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_frames_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_frames_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_frames_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_frames_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_frames_lifted_o2.obj" "/Fe${cpu_fuzz_frames_o2}"
        DEPENDS "${cpu_fuzz_frames_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_frames_lifted_o2 ALL DEPENDS "${cpu_fuzz_frames_o2}")
    add_test(NAME cpu_aot_fuzz_frames COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_FRAMES_SEED}" "${CPU_FUZZ_FRAMES_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_frames>" "$<TARGET_FILE:cpu_fuzz_frames_lifted>" "${cpu_fuzz_frames_o2}"
        --area frames --mutant "$<TARGET_FILE:cpu_fuzz_frames_mutant>")
    set_tests_properties(cpu_aot_fuzz_frames PROPERTIES TIMEOUT 60)
    # Direct calls and tail jumps to leaf and frame callees, shared callees and a planted call retarget.
    set(CPU_FUZZ_CALLS_SEED "0xCA11" CACHE STRING "Seed for the CPU differential fuzz call test")
    set(CPU_FUZZ_CALLS_FUNCTIONS "16" CACHE STRING "Number of generated callers in the CPU differential fuzz call test")
    set(cpu_fuzz_calls_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_calls.asm")
    set(cpu_fuzz_calls_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_calls.def")
    add_custom_command(OUTPUT "${cpu_fuzz_calls_asm}" "${cpu_fuzz_calls_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_CALLS_SEED}" "${CPU_FUZZ_CALLS_FUNCTIONS}" "${cpu_fuzz_calls_asm}"
            "${cpu_fuzz_calls_def}" --area calls
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_calls SHARED "${cpu_fuzz_calls_asm}" "${cpu_fuzz_calls_def}")
    set_target_properties(cpu_fuzz_calls PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_calls PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_calls_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_calls_lifted.cpp")
    set(cpu_fuzz_calls_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_calls_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_calls_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_CALLS_SEED}" "${CPU_FUZZ_CALLS_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_calls>"
                "${cpu_fuzz_calls_${variant}}" --area calls ${mutant_flag}
            DEPENDS cpu_fuzz_calls tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_calls_${variant} SHARED "${cpu_fuzz_calls_${variant}}")
        target_compile_features(cpu_fuzz_calls_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_calls_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_calls_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_calls_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_calls_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_calls_lifted_o2.obj" "/Fe${cpu_fuzz_calls_o2}"
        DEPENDS "${cpu_fuzz_calls_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_calls_lifted_o2 ALL DEPENDS "${cpu_fuzz_calls_o2}")
    add_test(NAME cpu_aot_fuzz_calls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_CALLS_SEED}" "${CPU_FUZZ_CALLS_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_calls>" "$<TARGET_FILE:cpu_fuzz_calls_lifted>" "${cpu_fuzz_calls_o2}"
        --area calls --mutant "$<TARGET_FILE:cpu_fuzz_calls_mutant>")
    set_tests_properties(cpu_aot_fuzz_calls PROPERTIES TIMEOUT 60)
    # Call chains through unexported callees, skipped conditional calls and tail jumps, with swapped call arguments planted.
    set(CPU_FUZZ_CHAINS_SEED "0xCA11" CACHE STRING "Seed for the CPU differential fuzz chain test")
    set(CPU_FUZZ_CHAINS_FUNCTIONS "16" CACHE STRING "Number of exported functions in the CPU differential fuzz chain test")
    set(cpu_fuzz_chains_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_chains.asm")
    set(cpu_fuzz_chains_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_chains.def")
    add_custom_command(OUTPUT "${cpu_fuzz_chains_asm}" "${cpu_fuzz_chains_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_CHAINS_SEED}" "${CPU_FUZZ_CHAINS_FUNCTIONS}" "${cpu_fuzz_chains_asm}"
            "${cpu_fuzz_chains_def}" --area chains
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_chains SHARED "${cpu_fuzz_chains_asm}" "${cpu_fuzz_chains_def}")
    set_target_properties(cpu_fuzz_chains PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_chains PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_chains_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_chains_lifted.cpp")
    set(cpu_fuzz_chains_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_chains_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_chains_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_CHAINS_SEED}" "${CPU_FUZZ_CHAINS_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_chains>"
                "${cpu_fuzz_chains_${variant}}" --area chains ${mutant_flag}
            DEPENDS cpu_fuzz_chains tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_chains_${variant} SHARED "${cpu_fuzz_chains_${variant}}")
        target_compile_features(cpu_fuzz_chains_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_chains_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_chains_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_chains_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_chains_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_chains_lifted_o2.obj" "/Fe${cpu_fuzz_chains_o2}"
        DEPENDS "${cpu_fuzz_chains_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_chains_lifted_o2 ALL DEPENDS "${cpu_fuzz_chains_o2}")
    add_test(NAME cpu_aot_fuzz_chains COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_CHAINS_SEED}" "${CPU_FUZZ_CHAINS_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_chains>" "$<TARGET_FILE:cpu_fuzz_chains_lifted>" "${cpu_fuzz_chains_o2}"
        --area chains --mutant "$<TARGET_FILE:cpu_fuzz_chains_mutant>")
    set_tests_properties(cpu_aot_fuzz_chains PROPERTIES TIMEOUT 60)

    set(CPU_FUZZ_SWITCHES_SEED "0x5717" CACHE STRING "Seed for the CPU differential fuzz switch test")
    set(CPU_FUZZ_SWITCHES_FUNCTIONS "48" CACHE STRING "Number of exported switches in the CPU differential fuzz switch test")
    set(cpu_fuzz_switches_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_switches.asm")
    set(cpu_fuzz_switches_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_switches.def")
    add_custom_command(OUTPUT "${cpu_fuzz_switches_asm}" "${cpu_fuzz_switches_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_SWITCHES_SEED}" "${CPU_FUZZ_SWITCHES_FUNCTIONS}" "${cpu_fuzz_switches_asm}"
            "${cpu_fuzz_switches_def}" --area switches
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_switches SHARED "${cpu_fuzz_switches_asm}" "${cpu_fuzz_switches_def}")
    set_target_properties(cpu_fuzz_switches PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_switches PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_switches_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_switches_lifted.cpp")
    set(cpu_fuzz_switches_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_switches_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_switches_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_SWITCHES_SEED}" "${CPU_FUZZ_SWITCHES_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_switches>"
                "${cpu_fuzz_switches_${variant}}" --area switches ${mutant_flag}
            DEPENDS cpu_fuzz_switches tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_switches_${variant} SHARED "${cpu_fuzz_switches_${variant}}")
        target_compile_features(cpu_fuzz_switches_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_switches_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_switches_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_switches_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_switches_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_switches_lifted_o2.obj" "/Fe${cpu_fuzz_switches_o2}"
        DEPENDS "${cpu_fuzz_switches_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_switches_lifted_o2 ALL DEPENDS "${cpu_fuzz_switches_o2}")
    add_test(NAME cpu_aot_fuzz_switches COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_SWITCHES_SEED}" "${CPU_FUZZ_SWITCHES_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_switches>" "$<TARGET_FILE:cpu_fuzz_switches_lifted>" "${cpu_fuzz_switches_o2}"
        --area switches --mutant "$<TARGET_FILE:cpu_fuzz_switches_mutant>")
    set_tests_properties(cpu_aot_fuzz_switches PROPERTIES TIMEOUT 60)

    # Scalar float and double arithmetic, compares, conversions and moves through cpu_sse_aot, with MIN and MAX swapped planted.
    set(CPU_FUZZ_SCALAR_FP_SEED "0xF10A" CACHE STRING "Seed for the CPU differential fuzz scalar float test")
    set(CPU_FUZZ_SCALAR_FP_FUNCTIONS "60" CACHE STRING "Number of exported scalar float functions in the CPU differential fuzz scalar float test")
    set(cpu_fuzz_scalar_fp_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_scalar_fp.asm")
    set(cpu_fuzz_scalar_fp_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_scalar_fp.def")
    add_custom_command(OUTPUT "${cpu_fuzz_scalar_fp_asm}" "${cpu_fuzz_scalar_fp_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_SCALAR_FP_SEED}" "${CPU_FUZZ_SCALAR_FP_FUNCTIONS}" "${cpu_fuzz_scalar_fp_asm}"
            "${cpu_fuzz_scalar_fp_def}" --area scalar_fp
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_scalar_fp SHARED "${cpu_fuzz_scalar_fp_asm}" "${cpu_fuzz_scalar_fp_def}")
    set_target_properties(cpu_fuzz_scalar_fp PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_scalar_fp PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_scalar_fp_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_scalar_fp_lifted.cpp")
    set(cpu_fuzz_scalar_fp_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_scalar_fp_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_scalar_fp_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_SCALAR_FP_SEED}" "${CPU_FUZZ_SCALAR_FP_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_scalar_fp>"
                "${cpu_fuzz_scalar_fp_${variant}}" --area scalar_fp ${mutant_flag}
            DEPENDS cpu_fuzz_scalar_fp tools/fuzz_cpu.py tools/cpu_sse_aot.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_scalar_fp_${variant} SHARED "${cpu_fuzz_scalar_fp_${variant}}")
        target_compile_features(cpu_fuzz_scalar_fp_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_scalar_fp_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_scalar_fp_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_scalar_fp_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_scalar_fp_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_scalar_fp_lifted_o2.obj" "/Fe${cpu_fuzz_scalar_fp_o2}"
        DEPENDS "${cpu_fuzz_scalar_fp_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_scalar_fp_lifted_o2 ALL DEPENDS "${cpu_fuzz_scalar_fp_o2}")
    add_test(NAME cpu_aot_fuzz_scalar_fp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_SCALAR_FP_SEED}" "${CPU_FUZZ_SCALAR_FP_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_scalar_fp>" "$<TARGET_FILE:cpu_fuzz_scalar_fp_lifted>" "${cpu_fuzz_scalar_fp_o2}"
        --area scalar_fp --mutant "$<TARGET_FILE:cpu_fuzz_scalar_fp_mutant>")
    set_tests_properties(cpu_aot_fuzz_scalar_fp PROPERTIES TIMEOUT 60)

    # Mid-body RSP changes (SUB and ADD RSP, PUSH and POP, arms, calls, RBP anchors), with a stale RSP planted.
    set(CPU_FUZZ_RSP_SEED "0xB0D1" CACHE STRING "Seed for the CPU differential fuzz mid-body RSP test")
    set(CPU_FUZZ_RSP_FUNCTIONS "36" CACHE STRING "Number of exported functions in the CPU differential fuzz mid-body RSP test")
    set(cpu_fuzz_rsp_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_rsp.asm")
    set(cpu_fuzz_rsp_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_rsp.def")
    add_custom_command(OUTPUT "${cpu_fuzz_rsp_asm}" "${cpu_fuzz_rsp_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_RSP_SEED}" "${CPU_FUZZ_RSP_FUNCTIONS}" "${cpu_fuzz_rsp_asm}"
            "${cpu_fuzz_rsp_def}" --area rsp
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_rsp SHARED "${cpu_fuzz_rsp_asm}" "${cpu_fuzz_rsp_def}")
    set_target_properties(cpu_fuzz_rsp PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_rsp PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_rsp_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_rsp_lifted.cpp")
    set(cpu_fuzz_rsp_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_rsp_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_rsp_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_RSP_SEED}" "${CPU_FUZZ_RSP_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_rsp>"
                "${cpu_fuzz_rsp_${variant}}" --area rsp ${mutant_flag}
            DEPENDS cpu_fuzz_rsp tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_rsp_${variant} SHARED "${cpu_fuzz_rsp_${variant}}")
        target_compile_features(cpu_fuzz_rsp_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_rsp_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_rsp_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_rsp_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_rsp_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_rsp_lifted_o2.obj" "/Fe${cpu_fuzz_rsp_o2}"
        DEPENDS "${cpu_fuzz_rsp_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_rsp_lifted_o2 ALL DEPENDS "${cpu_fuzz_rsp_o2}")
    add_test(NAME cpu_aot_fuzz_rsp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_RSP_SEED}" "${CPU_FUZZ_RSP_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_rsp>" "$<TARGET_FILE:cpu_fuzz_rsp_lifted>" "${cpu_fuzz_rsp_o2}"
        --area rsp --mutant "$<TARGET_FILE:cpu_fuzz_rsp_mutant>")
    set_tests_properties(cpu_aot_fuzz_rsp PROPERTIES TIMEOUT 60)

    # Counted loops with backward conditional branches, early exits and a nested loop, with every back edge retargeted planted.
    set(CPU_FUZZ_LOOPS_SEED "0x100F" CACHE STRING "Seed for the CPU differential fuzz loop test")
    set(CPU_FUZZ_LOOPS_FUNCTIONS "32" CACHE STRING "Number of exported functions in the CPU differential fuzz loop test")
    set(cpu_fuzz_loops_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_loops.asm")
    set(cpu_fuzz_loops_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_loops.def")
    add_custom_command(OUTPUT "${cpu_fuzz_loops_asm}" "${cpu_fuzz_loops_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_LOOPS_SEED}" "${CPU_FUZZ_LOOPS_FUNCTIONS}" "${cpu_fuzz_loops_asm}"
            "${cpu_fuzz_loops_def}" --area loops
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_loops SHARED "${cpu_fuzz_loops_asm}" "${cpu_fuzz_loops_def}")
    set_target_properties(cpu_fuzz_loops PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_loops PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_loops_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_loops_lifted.cpp")
    set(cpu_fuzz_loops_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_loops_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_loops_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_LOOPS_SEED}" "${CPU_FUZZ_LOOPS_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_loops>"
                "${cpu_fuzz_loops_${variant}}" --area loops ${mutant_flag}
            DEPENDS cpu_fuzz_loops tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_loops_${variant} SHARED "${cpu_fuzz_loops_${variant}}")
        target_compile_features(cpu_fuzz_loops_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_loops_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_loops_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_loops_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_loops_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_loops_lifted_o2.obj" "/Fe${cpu_fuzz_loops_o2}"
        DEPENDS "${cpu_fuzz_loops_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_loops_lifted_o2 ALL DEPENDS "${cpu_fuzz_loops_o2}")
    add_test(NAME cpu_aot_fuzz_loops COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_LOOPS_SEED}" "${CPU_FUZZ_LOOPS_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_loops>" "$<TARGET_FILE:cpu_fuzz_loops_lifted>" "${cpu_fuzz_loops_o2}"
        --area loops --mutant "$<TARGET_FILE:cpu_fuzz_loops_mutant>")
    set_tests_properties(cpu_aot_fuzz_loops PROPERTIES TIMEOUT 60)

    # Straight-line x87 code through the shared lowering's x87 profile, with FSUBR lowered as FSUB planted.
    set(CPU_FUZZ_X87_SEED "0x8087" CACHE STRING "Seed for the CPU differential fuzz x87 test")
    set(CPU_FUZZ_X87_FUNCTIONS "40" CACHE STRING "Number of exported functions in the CPU differential fuzz x87 test")
    set(cpu_fuzz_x87_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_x87.asm")
    set(cpu_fuzz_x87_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_x87.def")
    add_custom_command(OUTPUT "${cpu_fuzz_x87_asm}" "${cpu_fuzz_x87_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_X87_SEED}" "${CPU_FUZZ_X87_FUNCTIONS}" "${cpu_fuzz_x87_asm}"
            "${cpu_fuzz_x87_def}" --area x87
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_x87 SHARED "${cpu_fuzz_x87_asm}" "${cpu_fuzz_x87_def}")
    set_target_properties(cpu_fuzz_x87 PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_x87 PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_x87_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_x87_lifted.cpp")
    set(cpu_fuzz_x87_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_x87_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_x87_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_X87_SEED}" "${CPU_FUZZ_X87_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_x87>"
                "${cpu_fuzz_x87_${variant}}" --area x87 ${mutant_flag}
            DEPENDS cpu_fuzz_x87 tools/fuzz_cpu.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
                tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_x87_${variant} SHARED "${cpu_fuzz_x87_${variant}}")
        target_compile_features(cpu_fuzz_x87_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_x87_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_x87_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_x87_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_x87_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_x87_lifted_o2.obj" "/Fe${cpu_fuzz_x87_o2}"
        DEPENDS "${cpu_fuzz_x87_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_x87_lifted_o2 ALL DEPENDS "${cpu_fuzz_x87_o2}")
    add_test(NAME cpu_aot_fuzz_x87 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_X87_SEED}" "${CPU_FUZZ_X87_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_x87>" "$<TARGET_FILE:cpu_fuzz_x87_lifted>" "${cpu_fuzz_x87_o2}"
        --area x87 --mutant "$<TARGET_FILE:cpu_fuzz_x87_mutant>")
    set_tests_properties(cpu_aot_fuzz_x87 PROPERTIES TIMEOUT 60)

    # Bit tests, counts, scans, byte swaps and immediate shifts with their defined flags, with BTS and BTR swapped planted.
    set(CPU_FUZZ_BITS_SEED "0xB175" CACHE STRING "Seed for the CPU differential fuzz bit-operation test")
    set(CPU_FUZZ_BITS_FUNCTIONS "40" CACHE STRING "Number of exported functions in the CPU differential fuzz bit-operation test")
    set(cpu_fuzz_bits_asm "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_bits.asm")
    set(cpu_fuzz_bits_def "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_bits.def")
    add_custom_command(OUTPUT "${cpu_fuzz_bits_asm}" "${cpu_fuzz_bits_def}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" emit
            "${CPU_FUZZ_BITS_SEED}" "${CPU_FUZZ_BITS_FUNCTIONS}" "${cpu_fuzz_bits_asm}"
            "${cpu_fuzz_bits_def}" --area bits
        DEPENDS tools/fuzz_cpu.py VERBATIM)
    add_library(cpu_fuzz_bits SHARED "${cpu_fuzz_bits_asm}" "${cpu_fuzz_bits_def}")
    set_target_properties(cpu_fuzz_bits PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_fuzz_bits PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO /OPT:NOICF)
    set(cpu_fuzz_bits_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_bits_lifted.cpp")
    set(cpu_fuzz_bits_mutant "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_bits_mutant.cpp")
    foreach(variant lifted mutant)
        set(mutant_flag "")
        if(variant STREQUAL "mutant")
            set(mutant_flag "--mutant")
        endif()
        add_custom_command(OUTPUT "${cpu_fuzz_bits_${variant}}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" translate
                "${CPU_FUZZ_BITS_SEED}" "${CPU_FUZZ_BITS_FUNCTIONS}" "$<TARGET_FILE:cpu_fuzz_bits>"
                "${cpu_fuzz_bits_${variant}}" --area bits ${mutant_flag}
            DEPENDS cpu_fuzz_bits tools/fuzz_cpu.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py
                tools/cpu_call_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_fuzz_bits_${variant} SHARED "${cpu_fuzz_bits_${variant}}")
        target_compile_features(cpu_fuzz_bits_${variant} PRIVATE cxx_std_20)
    endforeach()
    set(cpu_fuzz_bits_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_bits_lifted_o2.dll")
    add_custom_command(OUTPUT "${cpu_fuzz_bits_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${cpu_fuzz_bits_lifted}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_fuzz_bits_lifted_o2.obj" "/Fe${cpu_fuzz_bits_o2}"
        DEPENDS "${cpu_fuzz_bits_lifted}" VERBATIM)
    add_custom_target(cpu_fuzz_bits_lifted_o2 ALL DEPENDS "${cpu_fuzz_bits_o2}")
    add_test(NAME cpu_aot_fuzz_bits COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/fuzz_cpu.py" check "${CPU_FUZZ_BITS_SEED}" "${CPU_FUZZ_BITS_FUNCTIONS}"
        "$<TARGET_FILE:cpu_fuzz_bits>" "$<TARGET_FILE:cpu_fuzz_bits_lifted>" "${cpu_fuzz_bits_o2}"
        --area bits --mutant "$<TARGET_FILE:cpu_fuzz_bits_mutant>")
    # A host without POPCNT, BMI1 or ABM cannot run the native exports as the translation describes them.
    set_tests_properties(cpu_aot_fuzz_bits PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_switch_addr32 switch_addr32)
    cpu_asm_fixture(cpu_switch_strings switch_strings)
    cpu_asm_fixture(cpu_string_probe string_probe)
    set(switch_strings_source "${CMAKE_CURRENT_BINARY_DIR}/cpu_switch_strings_lifted.cpp")
    add_custom_command(OUTPUT "${switch_strings_source}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/switch_strings_check.py"
            emit "$<TARGET_FILE:cpu_switch_strings>" "${switch_strings_source}"
        DEPENDS cpu_switch_strings tests/cpu/switch_strings_check.py tools/cpu_switch_aot.py
            tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
    add_library(cpu_switch_strings_lifted SHARED "${switch_strings_source}")
    set(switch_strings_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_switch_strings_lifted_o2.dll")
    add_custom_command(OUTPUT "${switch_strings_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${switch_strings_source}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_switch_strings_lifted_o2.obj" "/Fe${switch_strings_o2}"
        DEPENDS "${switch_strings_source}" VERBATIM)
    add_custom_target(cpu_switch_strings_lifted_o2 ALL DEPENDS "${switch_strings_o2}")
    set(switch_strings_mutants "${CMAKE_CURRENT_BINARY_DIR}/cpu_switch_strings_mutants.cpp")
    add_custom_command(OUTPUT "${switch_strings_mutants}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/switch_strings_check.py"
            mutants "$<TARGET_FILE:cpu_switch_strings>" "${switch_strings_mutants}"
        DEPENDS cpu_switch_strings tests/cpu/switch_strings_check.py tools/cpu_switch_aot.py
            tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
    set(switch_strings_mutants_dll "${CMAKE_CURRENT_BINARY_DIR}/cpu_switch_strings_mutants.dll")
    add_custom_command(OUTPUT "${switch_strings_mutants_dll}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${switch_strings_mutants}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_switch_strings_mutants.obj" "/Fe${switch_strings_mutants_dll}"
        DEPENDS "${switch_strings_mutants}" VERBATIM)
    add_custom_target(cpu_switch_strings_mutants ALL DEPENDS "${switch_strings_mutants_dll}")
    add_test(NAME cpu_aot_switch_strings COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_strings_check.py" check "$<TARGET_FILE:cpu_string_probe>"
        "$<TARGET_FILE:cpu_guarded_call>" "$<TARGET_FILE:cpu_switch_strings>"
        "$<TARGET_FILE:cpu_switch_strings_lifted>" "${switch_strings_o2}"
        "${switch_strings_mutants_dll}")
    set_tests_properties(cpu_aot_switch_strings PROPERTIES TIMEOUT 60
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_switch_strings.txt")
    cpu_translation(cpu_switch_addr32 cpu_switch_aot lea_wrap,lea_back,load_back,store_ahead)
    add_test(NAME cpu_aot_switch_addr32 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_addr32_check.py" "$<TARGET_FILE:cpu_switch_addr32>"
        "$<TARGET_FILE:cpu_switch_addr32_lifted>")
    cpu_asm_fixture(cpu_entry_order entry_order)
    cpu_translation(cpu_entry_order cpu_switch_aot square_tail,inc_square,pick_tail,branch_next)
    add_test(NAME cpu_aot_entry_order COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/entry_order_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_entry_order>" "$<TARGET_FILE:cpu_entry_order_lifted>")
    cpu_asm_fixture(cpu_dead_read dead_read)
    cpu_translation(cpu_dead_read cpu_switch_aot
        read_dead,cmp_dead,byte_dead,pair_dead,read_live,read_skip,sum_zero,add_in_place)
    # The same translation built with /O2, where the compiler removes a read that the generated C++ lets it remove.
    set(dead_read_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_read_lifted_o2.dll")
    add_custom_command(OUTPUT "${dead_read_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_read_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_read_lifted_o2.obj" "/Fe${dead_read_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_read_lifted.cpp" VERBATIM)
    add_custom_target(cpu_dead_read_lifted_o2 ALL DEPENDS "${dead_read_o2}")
    add_test(NAME cpu_aot_dead_reads COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/dead_read_check.py" "$<TARGET_FILE:cpu_guarded_call>"
        "$<TARGET_FILE:cpu_dead_read>" "$<TARGET_FILE:cpu_dead_read_lifted>" "${dead_read_o2}")
    # The same control for the shared integer lowering (ffx_version_query.lower, with its x87 profile).
    cpu_asm_fixture(cpu_lower_dead_read lower_dead_read)
    set(lower_dead_read_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_lower_dead_read_lifted.cpp")
    add_custom_command(OUTPUT "${lower_dead_read_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/lower_dead_read.py"
            emit "$<TARGET_FILE:cpu_lower_dead_read>" "${lower_dead_read_fixture}"
        DEPENDS cpu_lower_dead_read tests/cpu/lower_dead_read.py tools/ffx_version_query.py tools/x87_lower.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_lower_dead_read_lifted SHARED "${lower_dead_read_fixture}")
    set(lower_dead_read_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_lower_dead_read_lifted_o2.dll")
    add_custom_command(OUTPUT "${lower_dead_read_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /EHsc /LD "${lower_dead_read_fixture}"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_lower_dead_read_lifted_o2.obj" "/Fe${lower_dead_read_o2}"
        DEPENDS "${lower_dead_read_fixture}" VERBATIM)
    add_custom_target(cpu_lower_dead_read_lifted_o2 ALL DEPENDS "${lower_dead_read_o2}")
    add_test(NAME cpu_aot_lower_dead_reads COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/lower_dead_read.py" check "$<TARGET_FILE:cpu_guarded_call>"
        "$<TARGET_FILE:cpu_lower_dead_read>" "$<TARGET_FILE:cpu_lower_dead_read_lifted>" "${lower_dead_read_o2}")
    cpu_asm_fixture(cpu_narrow narrow)
    cpu_translation(cpu_narrow cpu_switch_aot
        byte_merge,word_ops,byte_shift,byte_unary,al_less,mixed_width,ax_copy,zx_byte,set_less,set_zx,store_only,store_ret0,self_loop,qword_ops,flag_results,imul3_fresh)
    add_test(NAME cpu_aot_narrow_returns COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/narrow_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_narrow>" "$<TARGET_FILE:cpu_narrow_lifted>")
    cpu_asm_fixture(cpu_fourth_arg fourth_arg)
    # ":4" gives an entry a fourth integer argument in R9; r9_scratch keeps the three-argument default.
    cpu_translation(cpu_fourth_arg cpu_switch_aot r9_mix:4,r9_loop:4,no_r9:4,r9_scratch)
    add_test(NAME cpu_aot_fourth_argument COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/fourth_arg_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_fourth_arg>" "$<TARGET_FILE:cpu_fourth_arg_lifted>"
        "${CMAKE_CURRENT_BINARY_DIR}/cpu_fourth_arg_lifted.cpp"
        "$<TARGET_FILE:cpu_narrow>" "$<TARGET_FILE:cpu_narrow_lifted>")
    cpu_asm_fixture(cpu_image_data image_data)
    # IMAGE_DATA: RIP-relative data addresses a mapping of the image that the test binds at run time.
    cpu_translation(cpu_image_data cpu_switch_aot
        read_counter,bump_counter,counter_address,load_counter_ptr,is_counter,set_vtable,vtable_entry,swap_scratch,load_through,switch_count,switch_only
        IMAGE_DATA)
    add_test(NAME cpu_aot_image_data COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/image_data_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_register_probe>" "$<TARGET_FILE:cpu_image_data>" "$<TARGET_FILE:cpu_image_data_lifted>")

    cpu_asm_fixture(cpu_frame frame)
    # frame_bound is translated and compiled but never called.
    cpu_translation(cpu_frame cpu_switch_aot
        push_loop,spill_widths,home_save,home_args,two_paths,home_spill,loop_counter,realloc_slot,anchored_frame,frame_bound)
    add_test(NAME cpu_aot_stack_frames COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/frame_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_frame>" "$<TARGET_FILE:cpu_frame_lifted>"
        "${CMAKE_CURRENT_BINARY_DIR}/cpu_frame_lifted.cpp")
    cpu_asm_fixture(cpu_leave leave)
    # LEAVE on a proven RBP anchor; the other exports of leave.asm exist only to be rejected.
    cpu_translation(cpu_leave cpu_switch_aot leave_frame,leave_lea,leave_join)
    add_test(NAME cpu_aot_leave COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/leave_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_leave>" "$<TARGET_FILE:cpu_leave_lifted>"
        "${CMAKE_CURRENT_BINARY_DIR}/cpu_leave_lifted.cpp")
    cpu_asm_fixture(cpu_calls calls)
    cpu_translation(cpu_calls cpu_switch_aot call_leaf,chain3,narrow_call,narrow_tail,tail_call,tail_after_frame,home_save_call)
    add_test(NAME cpu_aot_direct_calls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/calls_check.py" check "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_calls>" "$<TARGET_FILE:cpu_calls_lifted>")
    cpu_asm_fixture(cpu_recursion recursion)
    # The exports from tail_ping on exist only to be refused; the test translates each alone.
    cpu_translation(cpu_recursion cpu_switch_aot sum_export,parity_export,walk_export,fold_export)
    add_test(NAME cpu_aot_recursion COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/recursion_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_recursion>" "$<TARGET_FILE:cpu_recursion_lifted>")
    cpu_asm_fixture(cpu_stack_args stack_args)
    # The exports from unset_slot on exist only to be refused; the test translates each alone.
    cpu_translation(cpu_stack_args cpu_switch_aot call_six,call_seven,call_scratch,call_rec,call_eight,call_fill,call_edge,call_twelfth)
    add_test(NAME cpu_aot_stack_arguments COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/stack_args_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_stack_args>" "$<TARGET_FILE:cpu_stack_args_lifted>")
    cpu_asm_fixture(cpu_call_entries call_entries)
    cpu_translation(cpu_call_entries cpu_switch_aot entry_caller,entry_tail)
    add_test(NAME cpu_aot_call_entries COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/call_entries_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_call_entries>" "$<TARGET_FILE:cpu_call_entries_lifted>")
    # Callees without unwind data, bound by a [start, end) manifest from the source labels in the linker map.
    cpu_asm_fixture(cpu_bare_calls bare_calls)
    target_link_options(cpu_bare_calls PRIVATE "/MAP:${CMAKE_CURRENT_BINARY_DIR}/cpu_bare_calls.map")
    set(bare_ranges "${CMAKE_CURRENT_BINARY_DIR}/cpu_bare_calls_ranges.json")
    add_custom_command(OUTPUT "${bare_ranges}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/range_manifest.py" "$<TARGET_FILE:cpu_bare_calls>"
            "${CMAKE_CURRENT_BINARY_DIR}/cpu_bare_calls.map" "${bare_ranges}" bare_mix bare_low
        DEPENDS cpu_bare_calls tools/range_manifest.py VERBATIM)
    cpu_translation(cpu_bare_calls cpu_switch_aot call_bare,twice_bare,tail_bare RANGES "${bare_ranges}")
    add_test(NAME cpu_aot_bound_callees COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bare_calls_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_bare_calls>" "$<TARGET_FILE:cpu_bare_calls_lifted>" "${bare_ranges}"
        "${CMAKE_CURRENT_BINARY_DIR}/cpu_bare_calls.map")
    cpu_asm_fixture(cpu_wide_arith wide_arith)
    cpu_translation(cpu_wide_arith cpu_switch_aot
        div32,idiv32,div64,udiv128,idiv64,mul64,imul64_1,mul32,imul32,mul8,mul16,widen,sign_dx)
    add_test(NAME cpu_aot_wide_arithmetic COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/wide_arith_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_wide_arith>" "$<TARGET_FILE:cpu_wide_arith_lifted>")
    cpu_asm_fixture(cpu_switch_rotates switch_rotates)
    cpu_translation(cpu_switch_rotates cpu_switch_aot
        rot_reg_cl_8,rot_reg_cl_16,rot_reg_cl_32,rot_reg_cl_64,rot_imm_1,rot_imm_edge,rot_mem_cl_8_16,rot_mem_cl_32_64,rot_mem_imm,rot_narrow_ret)
    add_test(NAME cpu_aot_switch_rotates COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_rotates_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_rotates>" "$<TARGET_FILE:cpu_switch_rotates_lifted>")
    cpu_asm_fixture(cpu_switch_shift_flags switch_shift_flags)
    cpu_translation(cpu_switch_shift_flags cpu_switch_aot
        shl1_8,shr1_8,sar1_8,shl1_16,shr1_16,sar1_16,shl1_32,shr1_32,sar1_32,shl1_64,shr1_64,sar1_64,shln_8,shrn_8,sarn_8,shln_16,shrn_16,sarn_16,shln_32,shrn_32,sarn_32,shln_64,shrn_64,sarn_64,shlw_16,sarw_8,shlw_64,shln_32m,jcc_shl64_o,jcc_shr32_b,jcc_sar16_s,jcc_shl8_be,jcc_sar64_g,jcc_shr8_ge,jcc_shrn_np,cmov_shift)
    add_test(NAME cpu_aot_switch_shift_flags COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_shift_flags_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_shift_flags>" "$<TARGET_FILE:cpu_switch_shift_flags_lifted>")
    cpu_asm_fixture(cpu_switch_sal switch_sal)
    cpu_translation(cpu_switch_sal cpu_switch_aot
        sal_reg_cl_8,sal_reg_cl_16,sal_reg_cl_32,sal_reg_cl_64,sal_mem_8_16,sal_mem_32_64,sal_mem_imm_edge,sal1_8,sal1_16,sal1_32,sal1_64,sal1_32_imm1,sal1_16m,saln_8,saln_16,saln_32,saln_64,salw_64,saln_32m,jcc_sal64_o,jcc_sal8_be,cmov_sal,sal_narrow_ret,sal_nonvolatile_frame)
    add_test(NAME cpu_aot_switch_sal COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_sal_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_sal>" "$<TARGET_FILE:cpu_switch_sal_lifted>" "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_switch_sal PROPERTIES
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_switch_sal.txt")
    cpu_asm_fixture(cpu_switch_bit_tests switch_bit_tests)
    cpu_translation(cpu_switch_bit_tests cpu_switch_aot
        bt16_reg,bt32_reg,bt64_reg,bts16_reg,bts32_reg,bts64_reg,btr16_reg,btr32_reg,btr64_reg,btc16_reg,btc32_reg,btc64_reg,bt16_imm,bt32_imm,bt64_imm,bts16_imm,bts32_imm,bts64_imm,btr16_imm,btr32_imm,btr64_imm,btc16_imm,btc32_imm,btc64_imm,bt16_mem,bt32_mem,bt64_mem,bts16_mem,bts32_mem,bts64_mem,btr16_mem,btr32_mem,btr64_mem,btc16_mem,btc32_mem,btc64_mem,jcc_bt,jcc_btr_nc,cmov_bt)
    add_test(NAME cpu_aot_switch_bit_tests COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_bit_tests_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_bit_tests>" "$<TARGET_FILE:cpu_switch_bit_tests_lifted>")
    cpu_asm_fixture(cpu_switch_bit_string switch_bit_string)
    cpu_translation(cpu_switch_bit_string cpu_switch_aot
        bt16_string,bt32_string,bt64_string,bts16_string,bts32_string,bts64_string,btr16_string,btr32_string,btr64_string,btc16_string,btc32_string,btc64_string,bt64_dead,btc64_alias)
    add_test(NAME cpu_aot_switch_bit_string COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_bit_string_check.py"
        "$<TARGET_FILE:cpu_switch_bit_string>" "$<TARGET_FILE:cpu_switch_bit_string_lifted>")
    cpu_asm_fixture(cpu_switch_bit_counts switch_bit_counts)
    cpu_translation(cpu_switch_bit_counts cpu_switch_aot
        popcnt16_reg,popcnt16_mem,popcnt32_reg,popcnt32_mem,popcnt64_reg,popcnt64_mem,lzcnt16_reg,lzcnt16_mem,lzcnt32_reg,lzcnt32_mem,lzcnt64_reg,lzcnt64_mem,tzcnt16_reg,tzcnt16_mem,tzcnt32_reg,tzcnt32_mem,tzcnt64_reg,tzcnt64_mem,jcc_tzcnt_b,jcc_lzcnt_e,jcc_popcnt_ne,cmov_counts)
    add_test(NAME cpu_aot_switch_bit_counts COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_bit_counts_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_bit_counts>" "$<TARGET_FILE:cpu_switch_bit_counts_lifted>")
    # A host without POPCNT, BMI1 or ABM cannot run the original as the reference describes it.
    set_tests_properties(cpu_aot_switch_bit_counts PROPERTIES SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_switch_bswap switch_bswap)
    cpu_translation(cpu_switch_bswap cpu_switch_aot
        bswap32_rax,bswap64_rax,bswap32_rcx,bswap64_rcx,bswap32_rdx,bswap64_rdx,bswap32_r8,bswap64_r8,bswap32_r9,bswap64_r9,bswap32_r10,bswap64_r10,bswap32_r11,bswap64_r11,bswap32_rbx,bswap64_rbx,bswap32_rbp,bswap64_rbp,bswap32_rsi,bswap64_rsi,bswap32_rdi,bswap64_rdi,bswap32_r12,bswap64_r12,bswap32_r13,bswap64_r13,bswap32_r14,bswap64_r14,bswap32_r15,bswap64_r15,bswap_mixed,jcc_bswap_b,cmov_bswap)
    add_test(NAME cpu_aot_switch_bswap COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_bswap_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_bswap>" "$<TARGET_FILE:cpu_switch_bswap_lifted>")
    cpu_asm_fixture(cpu_switch_fsgsbase_rdpid switch_fsgsbase_rdpid)
    cpu_translation(cpu_switch_fsgsbase_rdpid cpu_switch_aot
        "rdfsbase_32,rdfsbase_64,rdgsbase_32,rdgsbase_64,read_host_nonvolatile,rdpid_64,rdpid_twice,flag_preserve_fsgsbase_rdpid,unused_host_reads"
        HOST_CPU)
    add_test(NAME cpu_aot_switch_fsgsbase_rdpid COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_fsgsbase_rdpid_check.py"
        "$<TARGET_FILE:cpu_switch_fsgsbase_rdpid>"
        "$<TARGET_FILE:cpu_switch_fsgsbase_rdpid_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_switch_fsgsbase_rdpid PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_switch_fsgsbase_rdpid.txt")
    # BSF and BSR; the swapped build assembles three exports with the other scan and must follow the exchanged reference.
    foreach(variant IN ITEMS original swapped)
        cpu_asm_fixture(cpu_switch_bit_scans_${variant} switch_bit_scans)
        cpu_translation(cpu_switch_bit_scans_${variant} cpu_switch_aot
            bsf16_reg,bsf16_mem,bsf32_reg,bsf32_mem,bsf64_reg,bsf64_mem,bsr16_reg,bsr16_mem,bsr32_reg,bsr32_mem,bsr64_reg,bsr64_mem,bsr32_self,bsf16_self,jcc_bsf_e,jcc_bsr_ne,cmov_scans)
    endforeach()
    target_compile_definitions(cpu_switch_bit_scans_swapped PRIVATE SWAP_SCANS)
    add_test(NAME cpu_aot_switch_bit_scans COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/switch_bit_scans_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_switch_bit_scans_original>" "$<TARGET_FILE:cpu_switch_bit_scans_original_lifted>"
        "$<TARGET_FILE:cpu_switch_bit_scans_swapped_lifted>")
    # Divides whose results are unused: the translation is also built with /O2, where the compiler would remove a
    # divide that the generated C++ let it remove, and both builds are compared with the original's exception codes.
    cpu_asm_fixture(cpu_dead_div dead_div)
    cpu_translation(cpu_dead_div cpu_switch_aot div32_dead,idiv32_dead,udiv128_dead,idiv64_dead,div_skip)
    add_library(cpu_guarded_call SHARED tests/cpu/guarded_call.cpp)
    set(dead_div_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_div_lifted_o2.dll")
    add_custom_command(OUTPUT "${dead_div_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_div_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_div_lifted_o2.obj" "/Fe${dead_div_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_dead_div_lifted.cpp" VERBATIM)
    add_custom_target(cpu_dead_div_lifted_o2 ALL DEPENDS "${dead_div_o2}")
    add_test(NAME cpu_aot_dead_divides COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/dead_div_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_guarded_call>" "$<TARGET_FILE:cpu_dead_div>" "$<TARGET_FILE:cpu_dead_div_lifted>"
        "${dead_div_o2}")
    set(cpu_avx2_exports
        "op_broadcasti128,op_extracti128_lo,op_extracti128_hi,op_inserti128_lo,op_inserti128_hi,"
        "op_perm2i128_mix,op_perm2i128_swap,op_perm2i128_zero_lo,op_perm2i128_zero_hi,"
        "op_perm2i128_zero_both,op_perm2i128_ignored,op_pbroadcastb_xmm,op_pbroadcastb_ymm,"
        "op_pbroadcastw_xmm,op_pbroadcastw_ymm,op_pbroadcastd_xmm,op_pbroadcastd_ymm,"
        "op_pbroadcastq_xmm,op_pbroadcastq_ymm,op_permd,op_permps,op_permq,op_permq_dup,"
        "op_permpd,op_pblendd_xmm,op_pblendd_ymm,op_pblendd_ymm_all,op_pblendd_ymm_none,"
        "op_psllvd_xmm,op_psllvd_ymm,op_psllvq_xmm,op_psllvq_ymm,op_psravd_xmm,op_psravd_ymm,"
        "op_psrlvd_xmm,op_psrlvd_ymm,op_psrlvq_xmm,op_psrlvq_ymm,op_zeroupper,op_pipeline,"
        "op_movdqu_store128,op_movdqu_copy128,"
        "op_gatherdps_xmm,op_gatherdps_ymm,op_gatherdps_ymm_scale1_disp,op_gatherdpd_xmm,"
        "op_gatherdpd_ymm,op_gatherqps_xmm_vm64x,op_gatherqps_xmm_vm64y,op_gatherqpd_xmm,"
        "op_gatherqpd_ymm,op_pgatherdd_xmm,op_pgatherdd_ymm,op_pgatherdq_xmm,op_pgatherdq_ymm,"
        "op_pgatherqd_xmm_vm64x,op_pgatherqd_xmm_vm64y,op_pgatherqq_xmm,op_pgatherqq_ymm,"
        "op_pgatherdd_ymm_rdx,"
        "op_pmaskmovd_load_xmm,op_pmaskmovd_load_ymm,op_pmaskmovq_load_xmm,op_pmaskmovq_load_ymm,"
        "op_pmaskmovd_store_xmm,op_pmaskmovd_store_ymm,op_pmaskmovq_store_xmm,op_pmaskmovq_store_ymm")
    string(CONCAT cpu_avx2_exports ${cpu_avx2_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx2_regs_${variant} avx2_regs)
        cpu_translation(cpu_avx2_regs_${variant} cpu_avx2_aot "${cpu_avx2_exports}")
    endforeach()
    target_compile_definitions(cpu_avx2_regs_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_avx2_regs COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx2_regs_check.py"
        "$<TARGET_FILE:cpu_avx2_regs_original>"
        "$<TARGET_FILE:cpu_avx2_regs_original_lifted>"
        "$<TARGET_FILE:cpu_avx2_regs_altered_lifted>")
    set(cpu_avx2_mem_exports
        "op_extracti128_mem_lo,op_extracti128_mem_hi,op_extracti128_mem_disp,"
        "op_inserti128_mem_lo,op_inserti128_mem_hi_disp,op_perm2i128_mem,"
        "op_pbroadcastb_xmm_mem,op_pbroadcastb_ymm_mem,op_pbroadcastw_xmm_mem,op_pbroadcastw_ymm_mem,"
        "op_pbroadcastd_xmm_mem,op_pbroadcastd_ymm_mem,op_pbroadcastq_xmm_mem,op_pbroadcastq_ymm_mem,"
        "op_permd_mem,op_permps_mem,op_permq_mem,op_permpd_mem,"
        "op_pblendd_xmm_mem,op_pblendd_ymm_mem,"
        "op_psllvd_xmm_mem,op_psllvd_ymm_mem,op_psllvq_xmm_mem,op_psllvq_ymm_mem,"
        "op_psravd_xmm_mem,op_psravd_ymm_mem,op_psrlvd_xmm_mem,op_psrlvd_ymm_mem,"
        "op_psrlvq_xmm_mem,op_psrlvq_ymm_mem,op_discarded_mem_read,op_mem_pipeline")
    string(CONCAT cpu_avx2_mem_exports ${cpu_avx2_mem_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx2_mem_${variant} avx2_mem)
        set(avx2_mem_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx2_mem_${variant}_lifted.cpp")
        add_custom_command(OUTPUT "${avx2_mem_lifted}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_avx2_aot.py"
                "$<TARGET_FILE:cpu_avx2_mem_${variant}>" "${cpu_avx2_mem_exports}" "${avx2_mem_lifted}" --mem-ops
            DEPENDS cpu_avx2_mem_${variant} tools/cpu_avx2_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        add_library(cpu_avx2_mem_${variant}_lifted SHARED "${avx2_mem_lifted}")
    endforeach()
    target_compile_definitions(cpu_avx2_mem_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_avx2_mem COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx2_mem_check.py"
        "$<TARGET_FILE:cpu_avx2_mem_original>"
        "$<TARGET_FILE:cpu_avx2_mem_original_lifted>"
        "$<TARGET_FILE:cpu_avx2_mem_altered_lifted>")
    set_tests_properties(cpu_aot_avx2_mem PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx2_mem.txt")
    set(cpu_avx_int_exports
        "op_pabsb,op_pabsw,op_pabsd,"
        "op_packsswb,op_packssdw,op_packusdw,"
        "op_paddb,op_paddq,op_paddsb,op_paddusb,op_paddusw,"
        "op_psubb,op_psubd,op_psubq,op_psubsb,op_psubsw,op_psubusb,op_psubusw,"
        "op_palignr_0,op_palignr_5,op_palignr_16,op_palignr_23,op_palignr_32,"
        "op_pblendvb,op_pblendw,op_pblendw_all,op_pblendw_none,"
        "op_pcmpeqb,op_pcmpeqw,op_pcmpeqd,op_pcmpeqq,op_pcmpgtb,op_pcmpgtw,op_pcmpgtd,op_pcmpgtq,"
        "op_pmaxsb,op_pmaxsd,op_pmaxub,op_pmaxuw,op_pmaxud,"
        "op_pminsb,op_pminsd,op_pminub,op_pminuw,op_pminud,"
        "op_phaddw,op_phaddd,op_phaddsw,op_phsubw,op_phsubd,op_phsubsw,op_phminposuw,"
        "op_pmaddwd,op_pmuldq,op_pmuludq,op_pmulhrsw,op_pmulhuw,op_pmulld,"
        "op_psadbw,op_mpsadbw_0,op_mpsadbw_3,op_mpsadbw_7_ignored,"
        "op_pshufhw,op_pshuflw,"
        "op_psignb,op_psignw,op_psignd,"
        "op_pmovsxbw,op_pmovsxbd,op_pmovsxbq,op_pmovsxwd,op_pmovsxwq,op_pmovsxdq,"
        "op_pmovzxbw,op_pmovzxbd,op_pmovzxbq,op_pmovzxwd,op_pmovzxwq,op_pmovzxdq,"
        "op_punpckldq,op_punpckhdq,op_punpcklqdq,op_punpckhqdq,"
        "op_pslld_xmm,op_psllq_xmm,op_psrld_xmm,op_psrlq_xmm,"
        "op_pslld_imm,op_pslld_imm_ovf,op_psllq_imm,op_psllq_imm_ovf,"
        "op_psrld_imm,op_psrld_imm_ovf,op_psrlq_imm,op_psrlq_imm_ovf,"
        "op_pmovmskb,"
        "op_pextrb_reg,op_pextrb_mem,op_pextrw_reg,op_pextrw_mem,"
        "op_pextrd_reg,op_pextrd_mem,op_pextrq_reg,op_pextrq_mem,"
        "op_pinsrb_reg,op_pinsrb_mem,op_pinsrw_reg,op_pinsrw_mem,"
        "op_pinsrd_reg,op_pinsrd_mem,op_pinsrq_reg,op_pinsrq_mem,"
        "op_zeroupper,op_zeroall,op_pipeline,op_movdqu_copy128,op_mov_store32,op_movdqu_regcopy,op_movdqu_store128,"
        "op_palignr_69,op_mpsadbw_6,op_pshuflw_1b,op_psllq_imm_129,op_pextrw_reg_2,op_pextrd_reg_2,"
        "op_pinsrb_reg_upper,op_pinsrw_reg_3,op_zeroupper_ymm1,op_movdqu_load128,"
        "op_palignr_255,op_pmovsxbq_wide_src,op_zeroupper_ymm2")
    string(CONCAT cpu_avx_int_exports ${cpu_avx_int_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_int_regs_${variant} avx_int_regs)
        cpu_translation(cpu_avx_int_regs_${variant} cpu_avx_int_aot "${cpu_avx_int_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_int_regs_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_avx_int_regs COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_regs_check.py"
        "$<TARGET_FILE:cpu_avx_int_regs_original>"
        "$<TARGET_FILE:cpu_avx_int_regs_original_lifted>"
        "$<TARGET_FILE:cpu_avx_int_regs_altered_lifted>")
    set(cpu_avx_int_ymm_addsub_exports
        "op_vpaddb_ymm,op_vpaddw_ymm,op_vpaddd_ymm,op_vpaddq_ymm,"
        "op_vpsubb_ymm,op_vpsubw_ymm,op_vpsubd_ymm,op_vpsubq_ymm,"
        "op_vpcmpeqb_ymm,op_vpcmpeqw_ymm,op_vpcmpeqd_ymm,op_vpcmpeqq_ymm,"
        "op_vpcmpgtb_ymm,op_vpcmpgtw_ymm,op_vpcmpgtd_ymm,op_vpcmpgtq_ymm,"
        "op_vpsubq_ymm_dst_src1,op_vpsubd_ymm_dst_src2,op_vpcmpgtq_ymm_dst_src2,op_vpaddw_ymm_all,"
        "op_vpcmpeqd_ymm_all,op_vpcmpgtb_ymm_all,op_vpaddq_ymm_then_xmm_subb,op_vpcmpeqw_ymm_then_xmm_addb,"
        "op_chain_ymm")
    string(CONCAT cpu_avx_int_ymm_addsub_exports ${cpu_avx_int_ymm_addsub_exports})
    cpu_asm_fixture(cpu_avx_int_ymm_addsub avx_int_ymm_addsub)
    cpu_translation(cpu_avx_int_ymm_addsub cpu_avx_int_aot "${cpu_avx_int_ymm_addsub_exports}")
    add_test(NAME cpu_aot_avx_int_ymm_addsub COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_addsub_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_addsub>"
        "$<TARGET_FILE:cpu_avx_int_ymm_addsub_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_addsub PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_avx_int_ymm_minmax_exports
        "op_vpmaxsb_ymm,op_vpmaxsw_ymm,op_vpmaxsd_ymm,op_vpmaxub_ymm,op_vpmaxuw_ymm,op_vpmaxud_ymm,"
        "op_vpminsb_ymm,op_vpminsw_ymm,op_vpminsd_ymm,op_vpminub_ymm,op_vpminuw_ymm,op_vpminud_ymm,"
        "op_vpmaxsd_ymm_dst_src2,op_vpminuw_ymm_dst_src1,op_vpmaxub_ymm_then_xmm_minsb")
    string(CONCAT cpu_avx_int_ymm_minmax_exports ${cpu_avx_int_ymm_minmax_exports})
    cpu_asm_fixture(cpu_avx_int_ymm_minmax avx_int_ymm_minmax)
    cpu_translation(cpu_avx_int_ymm_minmax cpu_avx_int_aot "${cpu_avx_int_ymm_minmax_exports}")
    add_test(NAME cpu_aot_avx_int_ymm_minmax COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_minmax_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_minmax>"
        "$<TARGET_FILE:cpu_avx_int_ymm_minmax_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_minmax PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_avx_int_ymm_sat_exports
        "op_vpaddsb_ymm,op_vpaddsw_ymm,op_vpaddusb_ymm,op_vpaddusw_ymm,"
        "op_vpsubsb_ymm,op_vpsubsw_ymm,op_vpsubusb_ymm,op_vpsubusw_ymm,"
        "op_vpsubsb_ymm_dst_src1,op_vpsubsw_ymm_dst_src1,op_vpsubusb_ymm_dst_src1,op_vpsubusw_ymm_dst_src1,"
        "op_vpsubsb_ymm_dst_src2,op_vpsubsw_ymm_dst_src2,op_vpsubusb_ymm_dst_src2,op_vpsubusw_ymm_dst_src2,"
        "op_vpaddsb_ymm_all,op_vpaddusb_ymm_then_xmm_subsb")
    string(CONCAT cpu_avx_int_ymm_sat_exports ${cpu_avx_int_ymm_sat_exports})
    cpu_asm_fixture(cpu_avx_int_ymm_sat avx_int_ymm_sat)
    cpu_translation(cpu_avx_int_ymm_sat cpu_avx_int_aot "${cpu_avx_int_ymm_sat_exports}")
    add_test(NAME cpu_aot_avx_int_ymm_sat COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_sat_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_sat>"
        "$<TARGET_FILE:cpu_avx_int_ymm_sat_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_sat PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_avx_int_ymm_abs_sign_shuf_exports
        "op_vpabsb_ymm,op_vpabsw_ymm,op_vpabsd_ymm,op_vpsignb_ymm,op_vpsignw_ymm,op_vpsignd_ymm,"
        "op_vpshufhw_ymm_1b,op_vpshufhw_ymm_93,op_vpshuflw_ymm_1b,op_vpshuflw_ymm_93,"
        "op_vpabsd_ymm_dst_src1,op_vpsignw_ymm_dst_src2,op_vpsignb_ymm_all,op_vpshufhw_ymm_dst_src1,"
        "op_vpabsb_ymm_then_xmm_vpsignb")
    string(CONCAT cpu_avx_int_ymm_abs_sign_shuf_exports ${cpu_avx_int_ymm_abs_sign_shuf_exports})
    cpu_asm_fixture(cpu_avx_int_ymm_abs_sign_shuf avx_int_ymm_abs_sign_shuf)
    cpu_translation(cpu_avx_int_ymm_abs_sign_shuf cpu_avx_int_aot "${cpu_avx_int_ymm_abs_sign_shuf_exports}")
    add_test(NAME cpu_aot_avx_int_ymm_abs_sign_shuf COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_abs_sign_shuf_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_abs_sign_shuf>"
        "$<TARGET_FILE:cpu_avx_int_ymm_abs_sign_shuf_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_abs_sign_shuf PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_avx_int_ymm_mul_sad_exports
        "op_vpmuldq_ymm,op_vpmuludq_ymm,op_vpmulhrsw_ymm,op_vpsadbw_ymm,"
        "op_vpmuldq_ymm_dst_src1,op_vpmuludq_ymm_dst_src2,op_vpmulhrsw_ymm_all,op_vpsadbw_ymm_dst_src2,"
        "op_vpmuldq_ymm_then_xmm_vpmuludq,op_chain_ymm_mul_sad")
    string(CONCAT cpu_avx_int_ymm_mul_sad_exports ${cpu_avx_int_ymm_mul_sad_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_int_ymm_mul_sad_${variant} avx_int_ymm_mul_sad)
        cpu_translation(cpu_avx_int_ymm_mul_sad_${variant} cpu_avx_int_aot "${cpu_avx_int_ymm_mul_sad_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_int_ymm_mul_sad_altered PRIVATE ALTER_YMM)
    add_test(NAME cpu_aot_avx_int_ymm_mul_sad COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_mul_sad_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_mul_sad_original>"
        "$<TARGET_FILE:cpu_avx_int_ymm_mul_sad_original_lifted>"
        "$<TARGET_FILE:cpu_avx_int_ymm_mul_sad_altered>"
        "$<TARGET_FILE:cpu_avx_int_ymm_mul_sad_altered_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_mul_sad PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_int_ymm_mul_sad.txt")
    set(cpu_avx_int_ymm_horizontal_exports
        "op_vphaddw_ymm,op_vphaddd_ymm,op_vphaddsw_ymm,op_vphsubw_ymm,op_vphsubd_ymm,op_vphsubsw_ymm,"
        "op_vphaddw_ymm_dst_src1,op_vphaddd_ymm_dst_src2,op_vphaddsw_ymm_all,op_vphsubw_ymm_dst_src2,"
        "op_vphaddsw_ymm_then_xmm_vphsubsw,op_chain_ymm_horizontal")
    string(CONCAT cpu_avx_int_ymm_horizontal_exports ${cpu_avx_int_ymm_horizontal_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_int_ymm_horizontal_${variant} avx_int_ymm_horizontal)
        cpu_translation(cpu_avx_int_ymm_horizontal_${variant} cpu_avx_int_aot "${cpu_avx_int_ymm_horizontal_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_int_ymm_horizontal_altered PRIVATE ALTER_YMM)
    add_test(NAME cpu_aot_avx_int_ymm_horizontal COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_horizontal_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_horizontal_original>"
        "$<TARGET_FILE:cpu_avx_int_ymm_horizontal_original_lifted>"
        "$<TARGET_FILE:cpu_avx_int_ymm_horizontal_altered>"
        "$<TARGET_FILE:cpu_avx_int_ymm_horizontal_altered_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_horizontal PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_int_ymm_horizontal.txt")
    # cpu_avx_int_ymm_pack_checks
    set(cpu_avx_int_ymm_pack_exports
        "op_vpacksswb_ymm,op_vpackssdw_ymm,op_vpackusdw_ymm,"
        "op_vpacksswb_ymm_dst_src1,op_vpackssdw_ymm_dst_src2,"
        "op_vpackusdw_ymm_all,op_vpacksswb_ymm_dst_src2,"
        "op_vpackusdw_ymm_then_xmm_vpacksswb,op_chain_ymm_pack")
    string(CONCAT cpu_avx_int_ymm_pack_exports ${cpu_avx_int_ymm_pack_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_int_ymm_pack_${variant} avx_int_ymm_pack)
        cpu_translation(cpu_avx_int_ymm_pack_${variant} cpu_avx_int_aot "${cpu_avx_int_ymm_pack_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_int_ymm_pack_altered PRIVATE ALTER_YMM)
    add_test(NAME cpu_aot_avx_int_ymm_pack COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_pack_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_pack_original>"
        "$<TARGET_FILE:cpu_avx_int_ymm_pack_original_lifted>"
        "$<TARGET_FILE:cpu_avx_int_ymm_pack_altered>"
        "$<TARGET_FILE:cpu_avx_int_ymm_pack_altered_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_pack PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_int_ymm_pack.txt")
    # cpu_avx_int_ymm_widen_unpack_checks
    set(cpu_avx_int_ymm_widen_unpack_exports
        "op_vpmovsxbw_ymm,op_vpmovsxbd_ymm,op_vpmovsxbq_ymm,op_vpmovsxwd_ymm,op_vpmovsxwq_ymm,op_vpmovsxdq_ymm,"
        "op_vpmovzxbw_ymm,op_vpmovzxbd_ymm,op_vpmovzxbq_ymm,op_vpmovzxwd_ymm,op_vpmovzxwq_ymm,op_vpmovzxdq_ymm,"
        "op_vpunpckldq_ymm,op_vpunpckhdq_ymm,op_vpunpcklqdq_ymm,op_vpunpckhqdq_ymm,"
        "op_vpmovsxbd_ymm_stale_dst,op_vpmovsxbw_ymm_alias,op_vpmovzxdq_ymm_alias,"
        "op_vpunpckldq_ymm_dst_src1,op_vpunpckhqdq_ymm_dst_src2,op_vpunpckhdq_ymm_all,"
        "op_vpmovsxwd_ymm_then_xmm_vpunpcklqdq,op_chain_ymm_widen_unpack")
    string(CONCAT cpu_avx_int_ymm_widen_unpack_exports ${cpu_avx_int_ymm_widen_unpack_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_int_ymm_widen_unpack_${variant} avx_int_ymm_widen_unpack)
        cpu_translation(cpu_avx_int_ymm_widen_unpack_${variant} cpu_avx_int_aot "${cpu_avx_int_ymm_widen_unpack_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_int_ymm_widen_unpack_altered PRIVATE ALTER_YMM)
    add_test(NAME cpu_aot_avx_int_ymm_widen_unpack COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_ymm_widen_unpack_check.py"
        "$<TARGET_FILE:cpu_avx_int_ymm_widen_unpack_original>"
        "$<TARGET_FILE:cpu_avx_int_ymm_widen_unpack_original_lifted>"
        "$<TARGET_FILE:cpu_avx_int_ymm_widen_unpack_altered>"
        "$<TARGET_FILE:cpu_avx_int_ymm_widen_unpack_altered_lifted>")
    set_tests_properties(cpu_aot_avx_int_ymm_widen_unpack PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_int_ymm_widen_unpack.txt")
    set(cpu_avx_move_exports
        "op_andpd_xmm,op_andpd_ymm,op_andps_xmm,op_andps_ymm,op_andnpd_xmm,op_andnpd_ymm,"
        "op_andnps_xmm,op_andnps_ymm,op_orpd_xmm,op_orpd_ymm,op_orps_xmm,op_orps_ymm,"
        "op_xorpd_xmm,op_xorpd_ymm,op_xorps_xmm,op_xorps_ymm,"
        "op_blendpd_xmm,op_blendpd_ymm,op_blendpd_ymm_all,op_blendpd_ymm_none,"
        "op_blendps_xmm,op_blendps_ymm,op_blendps_ymm_all,op_blendps_ymm_none,"
        "op_blendvpd_xmm,op_blendvpd_ymm,op_blendvps_xmm,op_blendvps_ymm,"
        "op_broadcastf128,op_broadcastsd_mem0,op_broadcastsd_mem1,op_broadcastsd_mem2,"
        "op_broadcastsd_mem3,op_broadcastsd_reg,op_broadcastss_xmm_mem0,op_broadcastss_xmm_mem1,"
        "op_broadcastss_xmm_mem2,op_broadcastss_xmm_mem3,op_broadcastss_ymm_mem4,op_broadcastss_ymm_mem5,"
        "op_broadcastss_ymm_mem6,op_broadcastss_ymm_mem7,op_broadcastss_xmm_reg,op_broadcastss_ymm_reg,"
        "op_extractf128_lo,op_extractf128_hi,op_insertf128_lo,op_insertf128_hi,"
        "op_extractps_lane0,op_extractps_lane1,op_extractps_lane2,op_extractps_lane3,"
        "op_insertps_s0d1_z0,op_insertps_s3d2_zmask,op_insertps_zero_all,"
        "op_perm2f128_mix,op_perm2f128_swap,op_perm2f128_zero_lo,op_perm2f128_zero_hi,"
        "op_perm2f128_zero_both,op_perm2f128_ignored,op_permilpd_imm_xmm,op_permilpd_imm_ymm,"
        "op_permilpd_imm_ymm_lo,op_permilpd_imm_ymm_hi,op_permilpd_var_xmm,op_permilpd_var_ymm,"
        "op_permilps_imm_xmm,op_permilps_imm_ymm,op_permilps_imm_ymm_lo,op_permilps_imm_ymm_hi,"
        "op_permilps_var_xmm,op_permilps_var_ymm,"
        "op_shufpd_xmm,op_shufpd_ymm,op_shufpd_ymm_lo,op_shufpd_ymm_hi,"
        "op_shufps_xmm,op_shufps_ymm,op_shufps_ymm_lo,op_shufps_ymm_hi,"
        "op_unpcklpd_xmm,op_unpcklpd_ymm,op_unpckhpd_xmm,op_unpckhpd_ymm,"
        "op_unpcklps_xmm,op_unpcklps_ymm,op_unpckhps_xmm,op_unpckhps_ymm,"
        "op_movapd_xmm,op_movapd_ymm,op_movapd_store128,"
        "op_movupd_xmm,op_movupd_ymm,op_movupd_store128,"
        "op_lddqu_xmm,op_lddqu_ymm,op_movntdq_xmm,op_movntdq_ymm,op_movntdqa_xmm,op_movntdqa_ymm,"
        "op_movntpd_xmm,op_movntpd_ymm,op_movntps_xmm,op_movntps_ymm,"
        "op_movddup_xmm,op_movddup_ymm,op_movshdup_xmm,op_movshdup_ymm,op_movsldup_xmm,op_movsldup_ymm,"
        "op_movhlps,op_movlhps,op_movhpd_load,op_movhpd_store,op_movhps_load,op_movhps_store,"
        "op_movlpd_load,op_movlpd_store,op_movlps_load,op_movlps_store,"
        "op_movsd_load,op_movsd_store,op_movsd_reg,op_movss_load,op_movss_store,op_movss_reg,"
        "op_movmskpd_xmm,op_movmskpd_ymm,op_movmskps_xmm,op_movmskps_ymm,"
        "op_maskmovps_load_xmm,op_maskmovps_load_ymm,op_maskmovpd_load_xmm,op_maskmovpd_load_ymm,"
        "op_maskmovps_store_xmm,op_maskmovps_store_ymm,op_maskmovpd_store_xmm,op_maskmovpd_store_ymm,"
        "op_zeroupper,op_pipeline,op_mov_load32,"
        "op_zeroupper_ymm1,op_movapd_xmm_dirty,op_mov_store32,op_insertps_s2d3_z1,"
        "op_extractps_w1_lane2,op_shufpd_xmm_sel1,op_shufps_ymm_sel2,op_negdisp_load")
    string(CONCAT cpu_avx_move_exports ${cpu_avx_move_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_move_regs_${variant} avx_move_regs)
        cpu_translation(cpu_avx_move_regs_${variant} cpu_avx_move_aot "${cpu_avx_move_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_move_regs_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_avx_move_regs COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_move_regs_check.py"
        "$<TARGET_FILE:cpu_avx_move_regs_original>"
        "$<TARGET_FILE:cpu_avx_move_regs_original_lifted>"
        "$<TARGET_FILE:cpu_avx_move_regs_altered_lifted>")
    set(cpu_avx_move_mem_exports
        "op_andpd_mem128,op_andps_mem128,op_andnpd_mem128,op_andnps_mem128,"
        "op_orpd_mem128,op_orps_mem128,op_xorpd_mem128,op_xorps_mem128,"
        "op_andpd_mem256,op_andps_mem256,op_andnpd_mem256,op_andnps_mem256,"
        "op_orpd_mem256,op_orps_mem256,op_xorpd_mem256,op_xorps_mem256")
    string(CONCAT cpu_avx_move_mem_exports ${cpu_avx_move_mem_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_move_mem_${variant} avx_move_mem)
        cpu_translation(cpu_avx_move_mem_${variant} cpu_avx_move_aot "${cpu_avx_move_mem_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_move_mem_altered PRIVATE ALTER_MUT)
    add_test(NAME cpu_aot_avx_move_mem COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_move_mem_check.py"
        "$<TARGET_FILE:cpu_avx_move_mem_original>"
        "$<TARGET_FILE:cpu_avx_move_mem_original_lifted>"
        "$<TARGET_FILE:cpu_avx_move_mem_altered_lifted>")
    set_tests_properties(cpu_aot_avx_move_mem PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_avx_move_ext_mem_exports
        "op_vblendpd_xmm_mem,op_vblendpd_ymm_mem,op_vblendps_xmm_mem,op_vblendps_ymm_mem,"
        "op_vblendvpd_xmm_mem,op_vblendvpd_ymm_mem,op_vblendvps_xmm_mem,op_vblendvps_ymm_mem,"
        "op_vextractf128_mem_lo,op_vextractf128_mem_hi,op_vextractf128_mem_disp,"
        "op_vinsertf128_mem_lo,op_vinsertf128_mem_hi,op_vextractps_mem,op_vinsertps_mem,"
        "op_vperm2f128_mem,op_vpermilpd_imm_xmm_mem,op_vpermilpd_imm_ymm_mem,op_vpermilpd_var_ymm_mem,"
        "op_vpermilps_imm_xmm_mem,op_vpermilps_imm_ymm_mem,op_vpermilps_var_ymm_mem,"
        "op_vshufpd_xmm_mem,op_vshufpd_ymm_mem,op_vshufps_xmm_mem,op_vshufps_ymm_mem,"
        "op_vunpcklpd_xmm_mem,op_vunpcklpd_ymm_mem,op_vunpckhpd_xmm_mem,op_vunpckhpd_ymm_mem,"
        "op_vunpcklps_xmm_mem,op_vunpcklps_ymm_mem,op_vunpckhps_xmm_mem,op_vunpckhps_ymm_mem,"
        "op_vmovddup_xmm_mem,op_vmovddup_ymm_mem,op_vmovshdup_xmm_mem,op_vmovshdup_ymm_mem,"
        "op_vmovsldup_xmm_mem,op_vmovsldup_ymm_mem,op_discarded_mem_read")
    string(CONCAT cpu_avx_move_ext_mem_exports ${cpu_avx_move_ext_mem_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_move_ext_mem_${variant} avx_move_ext_mem)
        set(avx_move_ext_mem_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_move_ext_mem_${variant}_lifted.cpp")
        add_custom_command(OUTPUT "${avx_move_ext_mem_lifted}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_avx_move_aot.py"
                "$<TARGET_FILE:cpu_avx_move_ext_mem_${variant}>" "${cpu_avx_move_ext_mem_exports}"
                "${avx_move_ext_mem_lifted}" --mem-ops
            DEPENDS cpu_avx_move_ext_mem_${variant} tools/cpu_avx_move_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        add_library(cpu_avx_move_ext_mem_${variant}_lifted SHARED "${avx_move_ext_mem_lifted}")
    endforeach()
    target_compile_definitions(cpu_avx_move_ext_mem_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_avx_move_ext_mem COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_move_ext_mem_check.py"
        "$<TARGET_FILE:cpu_avx_move_ext_mem_original>"
        "$<TARGET_FILE:cpu_avx_move_ext_mem_original_lifted>"
        "$<TARGET_FILE:cpu_avx_move_ext_mem_altered_lifted>")
    set_tests_properties(cpu_aot_avx_move_ext_mem PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_move_ext_mem.txt")
    set(cpu_avx_pcmpstr_exports
        "vpcmpestri_ub_eqany_pos_lsb,vpcmpestri_sw_ranges_neg_msb,vpcmpestri_sb_eqeach_mpos_msb,"
        "vpcmpestri_uw_eqord_mneg_lsb,vpcmpestri_mem_ub_eqany_pos_lsb,vpcmpestri_alias_xmm0,"
        "vpcmpestrm_ub_eqany_pos_bit,vpcmpestrm_sb_ranges_neg_exp,vpcmpestrm_uw_eqeach_mpos_exp,"
        "vpcmpestrm_sw_eqord_mneg_bit,vpcmpestrm_mem_ub_eqany_exp,vpcmpestrm_xmm0_self,"
        "vpcmpistri_ub_eqord_pos_lsb,vpcmpistri_sb_ranges_mneg_msb,vpcmpistri_uw_eqany_neg_msb,"
        "vpcmpistri_sw_eqeach_mpos_lsb,vpcmpistri_mem_ub_eqany_pos_lsb,"
        "vpcmpistrm_ub_eqeach_pos_exp,vpcmpistrm_sw_eqany_mneg_exp,vpcmpistrm_uw_ranges_mpos_bit,"
        "vpcmpistrm_sb_eqord_neg_bit,vpcmpistrm_mem_ub_eqord_exp,vpcmpistrm_discarded_read")
    string(CONCAT cpu_avx_pcmpstr_exports ${cpu_avx_pcmpstr_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_pcmpstr_${variant} avx_pcmpstr)
        cpu_translation(cpu_avx_pcmpstr_${variant} cpu_avx_pcmpstr_aot "${cpu_avx_pcmpstr_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_pcmpstr_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_avx_pcmpstr COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_pcmpstr.py"
        "$<TARGET_FILE:cpu_avx_pcmpstr_original>"
        "$<TARGET_FILE:cpu_avx_pcmpstr_original_lifted>"
        "$<TARGET_FILE:cpu_avx_pcmpstr_altered_lifted>")
    set_tests_properties(cpu_aot_avx_pcmpstr PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_xsave_state_original_exports
        "op_xrstor_xsave,op_xrstor64_xsave64,op_xrstor_xsave64,op_xrstor64_xsave,"
        "op_xrstor64_disp,op_xrstor64_mask_sse,op_vzeroupper_xsave64,op_pipeline,op_xrstor64_xsave64_avx,"
        "op_xrstor64_movq_read_xsave64,"
        "op_discarded_read,op_xrstor64_xsavec,op_xrstor64_xsavec64,"
        "op_xrstor64_xsavec64_sse,op_xrstor64_xsavec64_x87_avx,op_xsavec64_dynmask,"
        "op_xrstor64_xsaveopt,op_xrstor64_xsaveopt64,op_xrstor64_xsaveopt64_sse,"
        "op_xrstor64_xsaveopt64_x87_avx,op_xrstor64_xsaveopt64_avx,op_xsaveopt64_dynmask,"
        "op_xrstor64_avx_xsaveopt64_avx")
    string(CONCAT cpu_xsave_state_original_exports ${cpu_xsave_state_original_exports})
    set(cpu_xsave_state_altered_exports
        "op_xrstor64_xsave64,op_xrstor_xsave64,op_xrstor64_disp,op_pipeline,"
        "op_xrstor64_xsavec64,op_xrstor64_xsavec64_sse,"
        "op_xrstor64_xsaveopt64,op_xrstor64_xsaveopt64_sse")
    string(CONCAT cpu_xsave_state_altered_exports ${cpu_xsave_state_altered_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_xsave_state_${variant} xsave_state)
        cpu_translation(cpu_xsave_state_${variant} cpu_xsave_aot "${cpu_xsave_state_${variant}_exports}")
    endforeach()
    target_compile_definitions(cpu_xsave_state_altered PRIVATE ALTER_OP)
    set(cpu_xsave_state_compacted_exports
        "op_xrstor64_sse_compacted_avx_xsaveopt64_avx,"
        "op_xsavec_xrstor_all,op_xsavec_xrstor_x87_avx,op_xsavec_xrstor_x87_sse,"
        "op_xsavec_xrstor_avx_only,op_xsavec_xrstor_sse_only,op_xrstor64_compacted_dynmask")
    string(CONCAT cpu_xsave_state_compacted_exports ${cpu_xsave_state_compacted_exports})
    set(cpu_xsave_state_compacted_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_xsave_state_compacted_lifted.cpp")
    add_custom_command(OUTPUT "${cpu_xsave_state_compacted_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_xsave_aot.py"
            "$<TARGET_FILE:cpu_xsave_state_original>" "${cpu_xsave_state_compacted_exports}"
            "${cpu_xsave_state_compacted_cpp}" --compacted-xrstor
        DEPENDS cpu_xsave_state_original tools/cpu_xsave_aot.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_xsave_state_compacted_lifted SHARED "${cpu_xsave_state_compacted_cpp}")
    set(cpu_xsave_state_compacted_altered_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_xsave_state_compacted_altered_lifted.cpp")
    add_custom_command(OUTPUT "${cpu_xsave_state_compacted_altered_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_xsave_aot.py"
            "$<TARGET_FILE:cpu_xsave_state_altered>" "op_xsavec_xrstor_all,op_xsavec_xrstor_avx_only"
            "${cpu_xsave_state_compacted_altered_cpp}" --compacted-xrstor
        DEPENDS cpu_xsave_state_altered tools/cpu_xsave_aot.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_xsave_state_compacted_altered_lifted SHARED "${cpu_xsave_state_compacted_altered_cpp}")
    set(cpu_xsave_state_canonical_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_xsave_state_canonical_lifted.cpp")
    add_custom_command(OUTPUT "${cpu_xsave_state_canonical_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_xsave_aot.py"
            "$<TARGET_FILE:cpu_xsave_state_original>" "op_xsave_only,op_xsave64_only,op_xrstor64_avx_xsaveopt64_avx"
            "${cpu_xsave_state_canonical_cpp}" --entry-state canonical --compacted-xrstor
        DEPENDS cpu_xsave_state_original tools/cpu_xsave_aot.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_xsave_state_canonical_lifted SHARED "${cpu_xsave_state_canonical_cpp}")
    set(cpu_xsave_state_canonical_altered_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_xsave_state_canonical_altered_lifted.cpp")
    add_custom_command(OUTPUT "${cpu_xsave_state_canonical_altered_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_xsave_aot.py"
            "$<TARGET_FILE:cpu_xsave_state_altered>" "op_xrstor64_mask_sse"
            "${cpu_xsave_state_canonical_altered_cpp}" --entry-state canonical
        DEPENDS cpu_xsave_state_altered tools/cpu_xsave_aot.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_xsave_state_canonical_altered_lifted SHARED "${cpu_xsave_state_canonical_altered_cpp}")
    add_test(NAME cpu_aot_xsave_state COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/xsave_state_check.py"
        "$<TARGET_FILE:cpu_xsave_state_original>"
        "$<TARGET_FILE:cpu_xsave_state_original_lifted>"
        "$<TARGET_FILE:cpu_xsave_state_altered_lifted>"
        "$<TARGET_FILE:cpu_xsave_state_canonical_lifted>"
        "$<TARGET_FILE:cpu_xsave_state_canonical_altered_lifted>"
        "$<TARGET_FILE:cpu_xsave_state_altered>"
        "$<TARGET_FILE:cpu_xsave_state_compacted_lifted>"
        "$<TARGET_FILE:cpu_xsave_state_compacted_altered_lifted>")
    set_tests_properties(cpu_aot_xsave_state PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_pcmpstr64_exports
        "pcmpestri64_ub_eqany_pos_lsb,pcmpestri64_sw_ranges_neg_msb,"
        "pcmpestri64_mem_sb_eqeach_mpos_msb,pcmpestri64_alias_xmm0,"
        "pcmpestrm64_ub_eqany_pos_bit,pcmpestrm64_sb_ranges_neg_exp,"
        "pcmpestrm64_mem_uw_eqord_mneg_exp,pcmpestrm64_xmm0_self,"
        "vpcmpestri64_ub_eqany_pos_lsb,vpcmpestri64_uw_eqord_mneg_lsb,"
        "vpcmpestri64_mem_sw_ranges_neg_msb,vpcmpestri64_alias_xmm0,"
        "vpcmpestrm64_ub_eqany_pos_bit,vpcmpestrm64_uw_eqeach_mpos_exp,"
        "vpcmpestrm64_mem_ub_eqany_exp,vpcmpestrm64_xmm0_self,"
        "vpcmpestrm64_discarded_read")
    string(CONCAT cpu_pcmpstr64_exports ${cpu_pcmpstr64_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_pcmpstr64_${variant} pcmpstr64)
        cpu_translation(cpu_pcmpstr64_${variant} cpu_pcmpstr64_aot "${cpu_pcmpstr64_exports}")
    endforeach()
    target_compile_definitions(cpu_pcmpstr64_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_pcmpstr64 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/pcmpstr64_check.py"
        "$<TARGET_FILE:cpu_pcmpstr64_original>"
        "$<TARGET_FILE:cpu_pcmpstr64_original_lifted>"
        "$<TARGET_FILE:cpu_pcmpstr64_altered_lifted>")
    set_tests_properties(cpu_aot_pcmpstr64 PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_pcmpstr64.txt")
    set(cpu_sse4a_exports
        "op_extrq_imm_basic,op_extrq_imm_zero_len,op_extrq_imm_high_bit,"
        "op_extrq_imm_mid,op_extrq_imm_bits76,"
        "op_extrq_reg_basic,op_extrq_reg_self,op_extrq_reg_xmm4_xmm5,"
        "op_insertq_imm_basic,op_insertq_imm_zero_len,op_insertq_imm_high_bit,"
        "op_insertq_imm_self,"
        "op_insertq_reg_basic,op_insertq_reg_self,op_insertq_reg_xmm4_xmm5,"
        "op_movntsd_aligned,op_movntsd_disp8,op_movntsd_unaligned,"
        "op_movntss_aligned,op_movntss_disp12,op_movntss_unaligned,"
        "op_pipeline,op_discarded_read,op_sse4a_discarded_read")
    string(CONCAT cpu_sse4a_exports ${cpu_sse4a_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse4a_${variant} sse4a)
        cpu_translation(cpu_sse4a_${variant} cpu_sse4a_aot "${cpu_sse4a_exports}")
    endforeach()
    target_compile_definitions(cpu_sse4a_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sse4a COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse4a_check.py"
        "$<TARGET_FILE:cpu_sse4a_original>"
        "$<TARGET_FILE:cpu_sse4a_original_lifted>"
        "$<TARGET_FILE:cpu_sse4a_altered_lifted>")
    set_tests_properties(cpu_aot_sse4a PROPERTIES
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_sse4a.txt")
    set(cpu_sysdesc_exports
        "op_sgdt,op_sgdt_disp,op_sidt,op_sidt_disp,"
        "op_sldt_r16,op_sldt_r32,op_sldt_r64,op_sldt_m16,op_sldt_m16_disp,"
        "op_str_r16,op_str_r32,op_str_r64,op_str_m16,op_str_m16_disp,"
        "op_smsw_r16,op_smsw_r32,op_smsw_r64,op_smsw_m16,op_smsw_m16_disp,"
        "op_sysdesc_flags_preserve,op_sysdesc_discarded_stores,op_sysdesc_unused_reg")
    string(CONCAT cpu_sysdesc_exports ${cpu_sysdesc_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sysdesc_${variant} sysdesc)
        cpu_translation(cpu_sysdesc_${variant} cpu_sysdesc_aot "${cpu_sysdesc_exports}" HOST_CPU)
    endforeach()
    target_compile_definitions(cpu_sysdesc_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sysdesc COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sysdesc_check.py"
        "$<TARGET_FILE:cpu_sysdesc_original>"
        "$<TARGET_FILE:cpu_sysdesc_original_lifted>"
        "$<TARGET_FILE:cpu_sysdesc_altered>"
        "$<TARGET_FILE:cpu_sysdesc_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_sysdesc PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_sysdesc.txt")
    set(cpu_sse2_exports
        "op_cmppd_0,op_cmppd_1,op_cmppd_2,op_cmppd_3,op_cmppd_4,op_cmppd_5,op_cmppd_6,op_cmppd_7,"
        "op_cmppd_mem,"
        "op_cmpsd_0,op_cmpsd_1,op_cmpsd_2,op_cmpsd_3,op_cmpsd_4,op_cmpsd_5,op_cmpsd_6,op_cmpsd_7,"
        "op_cmpsd_mem,op_cmpsd_mem_plus1,"
        "op_maxsd_reg,op_maxsd_mem,op_minsd_reg,op_minsd_mem,op_sqrtsd_reg,op_sqrtsd_mem,"
        "op_cvtsd2si_r32_reg,op_cvtsd2si_r64_reg,op_cvtsd2si_r32_mem,op_cvtsd2si_r64_mem,"
        "op_cvtdq2pd_reg,op_cvtdq2pd_mem,op_cvtdq2ps_reg,op_cvtdq2ps_mem,"
        "op_cvtpd2dq_reg,op_cvtpd2dq_mem,op_cvtpd2ps_reg,op_cvtpd2ps_mem,op_cvtpi2pd_mem,"
        "op_cvtps2dq_reg,op_cvtps2dq_mem,op_cvtps2pd_reg,op_cvtps2pd_mem,"
        "op_cvttpd2dq_reg,op_cvttpd2dq_mem,op_cvttps2dq_reg,op_cvttps2dq_mem,"
        "op_movapd_ls,op_movapd_reg,op_movdqa_ls,op_movdqa_reg,"
        "op_movhpd_load,op_movhpd_store,op_movlpd_load,op_movlpd_store,"
        "op_movhpd_load_plus1,op_movlpd_load_plus1,"
        "op_movhpd_store_plus1,op_movlpd_store_plus1,op_maxsd_mem_plus1,op_cvtsd2si_mem_plus1,"
        "op_movntdq,op_movntpd,op_movnti32,op_movnti64,"
        "op_lfence,op_mfence,op_pipeline")
    string(CONCAT cpu_sse2_exports ${cpu_sse2_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse2_regs_${variant} sse2_regs)
        target_sources(cpu_sse2_regs_${variant} PRIVATE tests/cpu/sse2_mxcsr_test.asm)
        cpu_translation(cpu_sse2_regs_${variant} cpu_sse2_aot "${cpu_sse2_exports}")
    endforeach()
    target_compile_definitions(cpu_sse2_regs_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sse2_regs COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_regs_check.py"
        "$<TARGET_FILE:cpu_sse2_regs_original>"
        "$<TARGET_FILE:cpu_sse2_regs_original_lifted>"
        "$<TARGET_FILE:cpu_sse2_regs_altered_lifted>")
    set(cpu_mmx_sse2_exports
        "op_cvtpd2pi_reg,op_cvtpd2pi_mem,op_cvtpd2pi_mem_disp,"
        "op_cvttpd2pi_reg,op_cvttpd2pi_mem,"
        "op_movdq2q,op_movq2dq,op_emms_standalone,"
        "op_movq_reg_mem,op_movdqa_reg_ls,op_movdqu_reg_ls,op_mmx_sse2_bridge,"
        "op_cvtpi2pd_reg,op_cvtpi2pd_mem,op_cvtpi2pd_mem_disp,"
        "op_cvtpi2pd_discarded_read,op_cvtpi2pd_bridge")
    string(CONCAT cpu_mmx_sse2_exports ${cpu_mmx_sse2_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_mmx_sse2_${variant} mmx_sse2)
        cpu_translation(cpu_mmx_sse2_${variant} cpu_mmx_sse2_aot "${cpu_mmx_sse2_exports}")
    endforeach()
    target_compile_definitions(cpu_mmx_sse2_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_mmx_sse2 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/mmx_sse2_check.py"
        "$<TARGET_FILE:cpu_mmx_sse2_original>"
        "$<TARGET_FILE:cpu_mmx_sse2_original_lifted>"
        "$<TARGET_FILE:cpu_mmx_sse2_altered_lifted>")
    set(cpu_sse_fp_exports
        "op_cmpps_0,op_cmpps_1,op_cmpps_2,op_cmpps_3,op_cmpps_4,op_cmpps_5,op_cmpps_6,op_cmpps_7,"
        "op_cmpps_mem,op_cmpps_mem_disp,op_cmpps_self,"
        "op_cmpss_0,op_cmpss_1,op_cmpss_2,op_cmpss_3,op_cmpss_4,op_cmpss_5,op_cmpss_6,op_cmpss_7,"
        "op_cmpss_mem,op_cmpss_mem_plus1,op_cmpss_self,"
        "op_movlps_load,op_movlps_store,op_movhps_load,op_movhps_store,"
        "op_movlps_load_plus1,op_movhps_load_plus1,op_movlps_store_plus1,op_movhps_store_plus1,"
        "op_movntps,op_movntps_disp16,op_movaps_reg,op_pipeline,op_discarded_read,"
        "op_addps,op_addps_mem,op_addps_mem_disp,op_addps_self,"
        "op_subps,op_subps_mem,op_subps_mem_disp,op_subps_self,"
        "op_mulps,op_mulps_mem,op_mulps_mem_disp,op_mulps_self,"
        "op_divps,op_divps_mem,op_divps_mem_disp,op_divps_self,"
        "op_minps,op_minps_mem,op_minps_mem_disp,op_minps_self,"
        "op_maxps,op_maxps_mem,op_maxps_mem_disp,op_maxps_self,"
        "op_sqrtps,op_sqrtps_mem,op_sqrtps_mem_disp,op_sqrtps_self,"
        "op_arith_pipeline")
    string(CONCAT cpu_sse_fp_exports ${cpu_sse_fp_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_fp_${variant} sse_fp)
        cpu_translation(cpu_sse_fp_${variant} cpu_sse_fp_aot "${cpu_sse_fp_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_fp_altered PRIVATE ALTER_IMM)
    cpu_asm_fixture(cpu_sse_fp_harness sse_fp_harness)
    add_test(NAME cpu_aot_sse_fp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_fp_check.py"
        "$<TARGET_FILE:cpu_sse_fp_original>"
        "$<TARGET_FILE:cpu_sse_fp_original_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_altered_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_harness>")
    set(cpu_sse_fp_logic_exports
        "op_andps,op_andps_mem,op_andps_mem_disp,op_andps_self,"
        "op_andnps,op_andnps_mem,op_andnps_mem_disp,op_andnps_self,"
        "op_orps,op_orps_mem,op_orps_mem_disp,op_orps_self,"
        "op_xorps,op_xorps_mem,op_xorps_mem_disp,op_xorps_self,"
        "op_xorps_zero_logic,op_xorps_zero_arith,op_logic_pipeline,op_logic_discarded_read")
    string(CONCAT cpu_sse_fp_logic_exports ${cpu_sse_fp_logic_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_fp_logic_${variant} sse_fp_logic)
        cpu_translation(cpu_sse_fp_logic_${variant} cpu_sse_fp_aot "${cpu_sse_fp_logic_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_fp_logic_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sse_fp_logic COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_fp_logic_check.py"
        "$<TARGET_FILE:cpu_sse_fp_logic_original>"
        "$<TARGET_FILE:cpu_sse_fp_logic_original_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_logic_altered>"
        "$<TARGET_FILE:cpu_sse_fp_logic_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set(cpu_sse_fp_pd_exports
        "op_addpd,op_addpd_mem,op_addpd_mem_disp,op_addpd_self,"
        "op_subpd,op_subpd_mem,op_subpd_mem_disp,op_subpd_self,"
        "op_mulpd,op_mulpd_mem,op_mulpd_mem_disp,op_mulpd_self,"
        "op_divpd,op_divpd_mem,op_divpd_mem_disp,op_divpd_self,"
        "op_minpd,op_minpd_mem,op_minpd_mem_disp,op_minpd_self,"
        "op_maxpd,op_maxpd_mem,op_maxpd_mem_disp,op_maxpd_self,"
        "op_sqrtpd,op_sqrtpd_mem,op_sqrtpd_mem_disp,op_sqrtpd_self,"
        "op_cmppd_0,op_cmppd_1,op_cmppd_2,op_cmppd_3,op_cmppd_4,op_cmppd_5,op_cmppd_6,op_cmppd_7,"
        "op_cmppd_mem,op_cmppd_mem_disp,op_cmppd_self,"
        "op_pd_pipeline")
    string(CONCAT cpu_sse_fp_pd_exports ${cpu_sse_fp_pd_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_fp_pd_${variant} sse_fp_pd)
        cpu_translation(cpu_sse_fp_pd_${variant} cpu_sse_fp_aot "${cpu_sse_fp_pd_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_fp_pd_altered PRIVATE ALTER_IMM)
    # The five checks of sse_fp_pd_check.py run as separate cases; cpu_aot_sse_fp_pd runs the rejections
    # and requires the other four.
    foreach(part IN ITEMS differential modes cmp_differential cmp_modes)
        x2w_add_check_part(cpu_aot_sse_fp_pd ${part} "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/sse_fp_pd_check.py"
            "$<TARGET_FILE:cpu_sse_fp_pd_original>"
            "$<TARGET_FILE:cpu_sse_fp_pd_original_lifted>"
            "$<TARGET_FILE:cpu_sse_fp_pd_altered_lifted>"
            "$<TARGET_FILE:cpu_sse_fp_harness>" ${part})
    endforeach()
    add_test(NAME cpu_aot_sse_fp_pd COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_fp_pd_check.py"
        "$<TARGET_FILE:cpu_sse_fp_pd_original>"
        "$<TARGET_FILE:cpu_sse_fp_pd_original_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_pd_altered_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_harness>" rejections)
    x2w_require_check_parts(cpu_aot_sse_fp_pd differential modes cmp_differential cmp_modes)
    # cpu_sse_fp_pd_logic_checks
    set(cpu_sse_fp_pd_logic_exports
        "op_andpd,op_andpd_mem,op_andpd_mem_disp,op_andpd_self,"
        "op_andnpd,op_andnpd_mem,op_andnpd_mem_disp,op_andnpd_self,"
        "op_orpd,op_orpd_mem,op_orpd_mem_disp,op_orpd_self,"
        "op_xorpd,op_xorpd_mem,op_xorpd_mem_disp,op_xorpd_self,"
        "op_xorpd_zero_logic,op_xorpd_zero_arith,op_pd_logic_pipeline,op_pd_logic_discarded_read")
    string(CONCAT cpu_sse_fp_pd_logic_exports ${cpu_sse_fp_pd_logic_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_fp_pd_logic_${variant} sse_fp_pd_logic)
        cpu_translation(cpu_sse_fp_pd_logic_${variant} cpu_sse_fp_aot "${cpu_sse_fp_pd_logic_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_fp_pd_logic_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sse_fp_pd_logic COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_fp_pd_logic_check.py"
        "$<TARGET_FILE:cpu_sse_fp_pd_logic_original>"
        "$<TARGET_FILE:cpu_sse_fp_pd_logic_original_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_pd_logic_altered>"
        "$<TARGET_FILE:cpu_sse_fp_pd_logic_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    # cpu_aot_sse_fp_pd_moves_cmp
    set(cpu_sse_fp_pd_moves_cmp_exports
        "op_cmpsd_0,op_cmpsd_1,op_cmpsd_2,op_cmpsd_3,op_cmpsd_4,op_cmpsd_5,op_cmpsd_6,op_cmpsd_7,"
        "op_cmpsd_mem,op_cmpsd_mem_plus1,op_cmpsd_self,"
        "op_movlpd_load,op_movlpd_store,op_movhpd_load,op_movhpd_store,"
        "op_movlpd_load_plus1,op_movhpd_load_plus1,op_movlpd_store_plus1,op_movhpd_store_plus1,"
        "op_movntpd,op_movntpd_disp16,op_pd_moves_cmp_pipeline,op_pd_moves_cmp_discarded_read")
    string(CONCAT cpu_sse_fp_pd_moves_cmp_exports ${cpu_sse_fp_pd_moves_cmp_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_fp_pd_moves_cmp_${variant} sse_fp_pd_moves_cmp)
        cpu_translation(cpu_sse_fp_pd_moves_cmp_${variant} cpu_sse_fp_aot "${cpu_sse_fp_pd_moves_cmp_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_fp_pd_moves_cmp_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sse_fp_pd_moves_cmp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_fp_pd_moves_cmp_check.py"
        "$<TARGET_FILE:cpu_sse_fp_pd_moves_cmp_original>"
        "$<TARGET_FILE:cpu_sse_fp_pd_moves_cmp_original_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_pd_moves_cmp_altered>"
        "$<TARGET_FILE:cpu_sse_fp_pd_moves_cmp_altered_lifted>"
        "$<TARGET_FILE:cpu_sse_fp_harness>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_sse_fp_pd_moves_cmp PROPERTIES
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_sse_fp_pd_moves_cmp.txt")
    set(cpu_avx_fp_move_exports
        "op_vmovq_xmm_xmm,op_vmovq_xmm_m64,op_vmovq_m64_xmm,op_vmovq_xmm_r64,op_vmovq_r64_xmm,"
        "op_vmaskmovdqu,op_pipeline,op_discarded_read,op_discarded_read64,"
        "op_vmovupd_xmm_load,op_vmovupd_ymm_load,op_vmovupd_xmm_store,op_vmovupd_ymm_store,"
        "op_vmovupd_xmm_reg,op_vmovupd_ymm_reg,op_vmovupd_xmm_regst,op_vmovupd_ymm_regst,"
        "op_vmovapd_xmm_load,op_vmovapd_ymm_load,op_vmovapd_xmm_store,op_vmovapd_ymm_store,"
        "op_vmovapd_xmm_reg,op_vmovapd_ymm_reg,op_vmovapd_xmm_regst,op_vmovapd_ymm_regst,"
        "op_pd_pipeline")
    string(CONCAT cpu_avx_fp_move_exports ${cpu_avx_fp_move_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_fp_move_${variant} avx_fp_move)
        cpu_translation(cpu_avx_fp_move_${variant} cpu_avx_fp_move_aot "${cpu_avx_fp_move_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_fp_move_altered PRIVATE ALTER_OP)
    add_test(NAME cpu_aot_avx_fp_move COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_fp_move_check.py"
        "$<TARGET_FILE:cpu_avx_fp_move_original>"
        "$<TARGET_FILE:cpu_avx_fp_move_original_lifted>"
        "$<TARGET_FILE:cpu_avx_fp_move_altered_lifted>")
    set_tests_properties(cpu_aot_avx_fp_move PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_avx_test_exports
        "op_vptest_xmm_reg,op_vptest_xmm_mem,op_vptest_ymm_reg,op_vptest_ymm_mem,"
        "op_vtestps_xmm_reg,op_vtestps_xmm_mem,op_vtestps_ymm_reg,op_vtestps_ymm_mem,"
        "op_vtestpd_xmm_reg,op_vtestpd_xmm_mem,op_vtestpd_ymm_reg,op_vtestpd_ymm_mem,"
        "op_vptest_ymm_after_xmm_zero,op_vtestps_ymm_after_xmm_zero,op_vtest_self,op_vtest_r8_store_reload")
    string(CONCAT cpu_avx_test_exports ${cpu_avx_test_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_test_${variant} avx_test)
        cpu_translation(cpu_avx_test_${variant} cpu_avx_test_aot "${cpu_avx_test_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_test_altered PRIVATE ALTER_TEST)
    add_test(NAME cpu_aot_avx_test COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_test_check.py"
        "$<TARGET_FILE:cpu_avx_test_original>"
        "$<TARGET_FILE:cpu_avx_test_original_lifted>"
        "$<TARGET_FILE:cpu_avx_test_altered>"
        "$<TARGET_FILE:cpu_avx_test_altered_lifted>")
    set_tests_properties(cpu_aot_avx_test PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_test.txt")
    set(cpu_sse_mmx_int_exports
        "op_pavgb_mm_reg,op_pavgb_mm_mem,op_pavgb_mm_mem_plus1,op_pavgb_mm_self,"
        "op_pavgw_mm_reg,op_pavgw_mm_mem,op_pavgw_mm_mem_plus1,op_pavgw_mm_self,"
        "op_pmulhuw_mm_reg,op_pmulhuw_mm_mem,op_pmulhuw_mm_mem_plus1,op_pmulhuw_mm_self,"
        "op_psadbw_mm_reg,op_psadbw_mm_mem,op_psadbw_mm_mem_plus1,op_psadbw_mm_self,"
        "op_pavgb_xmm_reg,op_pavgb_xmm_mem,op_pavgb_xmm_mem_disp,op_pavgb_xmm_self,"
        "op_pavgw_xmm_reg,op_pavgw_xmm_mem,op_pavgw_xmm_mem_disp,op_pavgw_xmm_self,"
        "op_pmulhuw_xmm_reg,op_pmulhuw_xmm_mem,op_pmulhuw_xmm_mem_disp,op_pmulhuw_xmm_self,"
        "op_psadbw_xmm_reg,op_psadbw_xmm_mem,op_psadbw_xmm_mem_disp,op_psadbw_xmm_self,"
        "op_mmx_int_pipeline,op_mmx_int_discarded_read")
    string(CONCAT cpu_sse_mmx_int_exports ${cpu_sse_mmx_int_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_mmx_int_${variant} sse_mmx_int)
        cpu_translation(cpu_sse_mmx_int_${variant} cpu_sse_mmx_aot "${cpu_sse_mmx_int_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_mmx_int_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sse_mmx_int COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_mmx_int_check.py"
        "$<TARGET_FILE:cpu_sse_mmx_int_original>"
        "$<TARGET_FILE:cpu_sse_mmx_int_original_lifted>"
        "$<TARGET_FILE:cpu_sse_mmx_int_altered>"
        "$<TARGET_FILE:cpu_sse_mmx_int_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set(cpu_sse_mmx_exports
        "op_cvtpi2ps_reg,op_cvtpi2ps_mem,op_cvtpi2ps_mem_plus1,"
        "op_cvtps2pi_reg,op_cvtps2pi_mem,op_cvtps2pi_mem_plus1,"
        "op_cvttps2pi_reg,op_cvttps2pi_mem,"
        "op_pshufw_reg_e4,op_pshufw_reg_1b,op_pshufw_reg_00,"
        "op_pshufw_reg_ff,op_pshufw_mem_4e,op_pshufw_mem_39,"
        "op_movntq,op_movntq_disp,op_movq_gpr_bridge,op_discarded_read,op_pipeline,"
        "op_maskmovq,op_maskmovdqu,op_maskmov_pipeline")
    string(CONCAT cpu_sse_mmx_exports ${cpu_sse_mmx_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_mmx_${variant} sse_mmx)
        cpu_translation(cpu_sse_mmx_${variant} cpu_sse_mmx_aot "${cpu_sse_mmx_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_mmx_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_sse_mmx COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_mmx_check.py"
        "$<TARGET_FILE:cpu_sse_mmx_original>"
        "$<TARGET_FILE:cpu_sse_mmx_original_lifted>"
        "$<TARGET_FILE:cpu_sse_mmx_altered_lifted>")
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_integer_flags_${variant} integer_flags)
        set(cpu_integer_flags_${variant}_lifted_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_integer_flags_${variant}_lifted.cpp")
        add_custom_command(OUTPUT "${cpu_integer_flags_${variant}_lifted_cpp}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/integer_flags_check.py"
                emit "$<TARGET_FILE:cpu_integer_flags_${variant}>" "${cpu_integer_flags_${variant}_lifted_cpp}"
            DEPENDS cpu_integer_flags_${variant} tests/cpu/integer_flags_check.py tools/ffx_version_query.py
                tools/x87_lower.py tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(cpu_integer_flags_${variant}_lifted SHARED "${cpu_integer_flags_${variant}_lifted_cpp}")
    endforeach()
    target_compile_definitions(cpu_integer_flags_altered PRIVATE ALTER_IMM)
    set(cpu_integer_flags_controls_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_integer_flags_controls.cpp")
    add_custom_command(OUTPUT "${cpu_integer_flags_controls_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/integer_flags_check.py"
            emit-controls "$<TARGET_FILE:cpu_integer_flags_original>" "${cpu_integer_flags_controls_cpp}"
        DEPENDS cpu_integer_flags_original tests/cpu/integer_flags_check.py tools/ffx_version_query.py
            tools/x87_lower.py tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
    add_library(cpu_integer_flags_controls SHARED "${cpu_integer_flags_controls_cpp}")
    # Reserved/hint NOP forms in the shared lowering (#1476): each accepted encoding must lower to a no-op,
    # and the neighbours that decode as another mnemonic (ENDBR64/32, CLDEMOTE, RDSSPD) must stay refused.
    add_test(NAME cpu_hint_nop COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/hint_nop_check.py")
    # Native-versus-lifted comparison for the same hint-NOP encodings: the native bytes and the lowered C++
    # are generated from one byte list, the memory forms are handed a PAGE_NOACCESS pointer, and two controls
    # prove the fixture can see a memory access and a register write at all (#1476).
    add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/hint_nop_fixture.cpp"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/hint_nop_fixture.py" emit
            "${CMAKE_CURRENT_BINARY_DIR}/hint_nop_fixture.cpp"
        DEPENDS tests/cpu/hint_nop_fixture.py tools/ffx_version_query.py VERBATIM)
    add_executable(cpu_hint_nop_fixture "${CMAKE_CURRENT_BINARY_DIR}/hint_nop_fixture.cpp")
    target_compile_features(cpu_hint_nop_fixture PRIVATE cxx_std_17)
    add_test(NAME cpu_hint_nop_fixture COMMAND cpu_hint_nop_fixture)
    set_tests_properties(cpu_hint_nop_fixture PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME cpu_aot_integer_flags COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/integer_flags_check.py" check
        "$<TARGET_FILE:cpu_integer_flags_original>"
        "$<TARGET_FILE:cpu_integer_flags_original_lifted>"
        "$<TARGET_FILE:cpu_integer_flags_altered_lifted>"
        "$<TARGET_FILE:cpu_integer_flags_controls>")
    set_tests_properties(cpu_aot_integer_flags PROPERTIES SKIP_RETURN_CODE 77)
    set(cpu_sse_fxsave_exports
        "op_fxrstor_fxsave,op_fxrstor64_fxsave64,op_fxrstor_fxsave64,"
        "op_fxrstor64_fxsave,op_fxrstor64_disp,op_pipeline,op_discarded_read,"
        "op_fxrstor64_movq_store,op_fxrstor64_movq_gpr")
    string(CONCAT cpu_sse_fxsave_exports ${cpu_sse_fxsave_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse_fxsave_${variant} sse_fxsave)
        cpu_translation(cpu_sse_fxsave_${variant} cpu_sse_fxsave_aot "${cpu_sse_fxsave_exports}")
    endforeach()
    target_compile_definitions(cpu_sse_fxsave_altered PRIVATE ALTER_OP)
    set(cpu_sse_fxsave_canonical_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse_fxsave_canonical_lifted.cpp")
    add_custom_command(OUTPUT "${cpu_sse_fxsave_canonical_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_sse_fxsave_aot.py"
            "$<TARGET_FILE:cpu_sse_fxsave_original>" "op_fxsave_only,op_fxsave64_only"
            "${cpu_sse_fxsave_canonical_cpp}" --entry-state canonical
        DEPENDS cpu_sse_fxsave_original tools/cpu_sse_fxsave_aot.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse_fxsave_canonical_lifted SHARED "${cpu_sse_fxsave_canonical_cpp}")
    add_test(NAME cpu_aot_sse_fxsave COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse_fxsave_check.py"
        "$<TARGET_FILE:cpu_sse_fxsave_original>"
        "$<TARGET_FILE:cpu_sse_fxsave_original_lifted>"
        "$<TARGET_FILE:cpu_sse_fxsave_altered_lifted>"
        "$<TARGET_FILE:cpu_sse_fxsave_canonical_lifted>")
    set_tests_properties(cpu_aot_sse_fxsave PROPERTIES SKIP_RETURN_CODE 77)
    # Import tail jumps: one caller per provider (named, altered return, ordinal-only), each translated twice:
    # tail_mix (three arguments) bound to mix3 with three, tail_choose (three) and tail_pass4 (four) to mix4 with four.
    set(tail_files)
    foreach(variant IN ITEMS named altered ordinal)
        set(provider cpu_tail_${variant}_provider)
        if(variant STREQUAL "ordinal")
            add_library(${provider} SHARED tests/cpu/tail_provider.cpp tests/cpu/tail_ordinal.def)
            set(mix3 SYMBOL "#3" LINK_NAME mix3)
            set(mix4 SYMBOL "#4" LINK_NAME mix4)
        else()
            add_library(${provider} SHARED tests/cpu/tail_provider.cpp tests/cpu/tail_provider.def)
            set(mix3 SYMBOL mix3)
            set(mix4 SYMBOL mix4)
        endif()
        cpu_asm_fixture(cpu_tail_${variant} tail_import)
        target_link_libraries(cpu_tail_${variant} PRIVATE ${provider})
        cpu_translation(cpu_tail_${variant} cpu_switch_aot tail_mix NAME cpu_tail_${variant}_mix3
            PROVIDER ${provider} ${mix3} IMPORT_ARGUMENTS 3 RETURN_BYTES 8)
        cpu_translation(cpu_tail_${variant} cpu_switch_aot tail_choose,tail_pass4:4 NAME cpu_tail_${variant}_mix4
            PROVIDER ${provider} ${mix4} IMPORT_ARGUMENTS 4 RETURN_BYTES 8)
        list(APPEND tail_files "$<TARGET_FILE:cpu_tail_${variant}>"
            "$<TARGET_FILE:cpu_tail_${variant}_mix3>" "${CMAKE_CURRENT_BINARY_DIR}/cpu_tail_${variant}_mix3.cpp"
            "$<TARGET_FILE:cpu_tail_${variant}_mix4>" "${CMAKE_CURRENT_BINARY_DIR}/cpu_tail_${variant}_mix4.cpp"
            "$<TARGET_FILE:${provider}>")
    endforeach()
    target_compile_definitions(cpu_tail_altered_provider PRIVATE ALTER_RETURN)
    add_test(NAME cpu_aot_import_tail_jump COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/tail_import_check.py" "$<TARGET_FILE:cpu_register_probe>" ${tail_files})
    # Ordinary import calls, linked against the named and the altered provider above. Each caller is translated
    # three times: call_keep,call_twice,outer_call,pass_result,read_then_call,call_then_read bound to mix3 with
    # three arguments and 8 guaranteed bytes, low_result to mix3 with 1, and thunk_call,thunk_tail,outer_tail to
    # mix4 with four arguments and 8.
    set(icall_files)
    foreach(variant IN ITEMS named altered)
        set(provider cpu_tail_${variant}_provider)
        cpu_asm_fixture(cpu_icall_${variant} import_calls)
        target_link_libraries(cpu_icall_${variant} PRIVATE ${provider})
        cpu_translation(cpu_icall_${variant} cpu_switch_aot
            call_keep,call_twice,outer_call,pass_result,read_then_call,call_then_read
            NAME cpu_icall_${variant}_mix3 PROVIDER ${provider} SYMBOL mix3 IMPORT_ARGUMENTS 3 RETURN_BYTES 8)
        cpu_translation(cpu_icall_${variant} cpu_switch_aot low_result
            NAME cpu_icall_${variant}_low PROVIDER ${provider} SYMBOL mix3 IMPORT_ARGUMENTS 3 RETURN_BYTES 1)
        cpu_translation(cpu_icall_${variant} cpu_switch_aot thunk_call,thunk_tail,outer_tail
            NAME cpu_icall_${variant}_mix4 PROVIDER ${provider} SYMBOL mix4 IMPORT_ARGUMENTS 4 RETURN_BYTES 8)
        list(APPEND icall_files "$<TARGET_FILE:cpu_icall_${variant}>"
            "$<TARGET_FILE:cpu_icall_${variant}_mix3>" "${CMAKE_CURRENT_BINARY_DIR}/cpu_icall_${variant}_mix3.cpp"
            "$<TARGET_FILE:cpu_icall_${variant}_low>" "${CMAKE_CURRENT_BINARY_DIR}/cpu_icall_${variant}_low.cpp"
            "$<TARGET_FILE:cpu_icall_${variant}_mix4>" "${CMAKE_CURRENT_BINARY_DIR}/cpu_icall_${variant}_mix4.cpp"
            "$<TARGET_FILE:${provider}>")
    endforeach()
    # The named caller's three translations built again with a separate cl /O2 command, as for cpu_aot_dead_reads.
    foreach(binding IN ITEMS mix3 low mix4)
        set(icall_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_icall_named_${binding}_o2.dll")
        add_custom_command(OUTPUT "${icall_o2}"
            COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_icall_named_${binding}.cpp"
                "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_icall_named_${binding}_o2.obj" "/Fe${icall_o2}"
                /link "$<TARGET_LINKER_FILE:cpu_tail_named_provider>"
            DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_icall_named_${binding}.cpp" cpu_tail_named_provider VERBATIM)
        add_custom_target(cpu_icall_named_${binding}_o2 ALL DEPENDS "${icall_o2}")
        list(APPEND icall_files "${icall_o2}")
    endforeach()
    add_test(NAME cpu_aot_import_calls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/import_calls_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_guarded_call>" ${icall_files})
    add_library(cpu_stack_output_provider SHARED tests/cpu/stack_output_provider.cpp)
    cpu_asm_fixture(cpu_stack_output stack_output)
    target_link_libraries(cpu_stack_output PRIVATE cpu_stack_output_provider)
    cpu_translation(cpu_stack_output cpu_switch_aot from_frame NAME cpu_stack_output_status
        PROVIDER cpu_stack_output_provider SYMBOL write_result IMPORT_ARGUMENTS 2 RETURN_BYTES 4 STACK_OUTPUT 1 8)
    cpu_translation(cpu_stack_output cpu_switch_aot from_rsp NAME cpu_stack_output_void
        PROVIDER cpu_stack_output_provider SYMBOL write_constant IMPORT_ARGUMENTS 1 RETURN_BYTES 0 STACK_OUTPUT 1 8)
    add_test(NAME cpu_aot_stack_output COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/stack_output_check.py" "$<TARGET_FILE:cpu_stack_output>"
        "$<TARGET_FILE:cpu_stack_output_provider>" "$<TARGET_FILE:cpu_stack_output_status>"
        "$<TARGET_FILE:cpu_stack_output_void>")
    # Two ordinary imports from two providers in one translation: mix3 from the tail-jump providers and fold4 from
    # slot_provider.cpp. One caller per provider pair: both named, mix3 altered, fold4 altered, and mix3 imported by
    # ordinal #3 (bound with the link name mix3) next to the named fold4. Each is translated once with mix3 bound with
    # three arguments and 8 guaranteed bytes and fold4 with four arguments and 2.
    foreach(variant IN ITEMS named altered)
        add_library(cpu_slot_${variant}_provider SHARED tests/cpu/slot_provider.cpp tests/cpu/slot_provider.def)
    endforeach()
    target_compile_definitions(cpu_slot_altered_provider PRIVATE ALTER_RETURN)
    set(slot_files)
    foreach(pair IN ITEMS "named;named;named" "first_altered;altered;named" "second_altered;named;altered"
                          "ordinal;ordinal;named")
        list(GET pair 0 variant)
        list(GET pair 1 first)
        list(GET pair 2 second)
        if(first STREQUAL "ordinal")
            set(mix3 SYMBOL "#3" LINK_NAME mix3)
        else()
            set(mix3 SYMBOL mix3)
        endif()
        cpu_asm_fixture(cpu_slots_${variant} two_slots)
        target_link_libraries(cpu_slots_${variant} PRIVATE cpu_tail_${first}_provider cpu_slot_${second}_provider)
        cpu_translation(cpu_slots_${variant} cpu_switch_aot route2,call_both,call_second NAME cpu_slots_${variant}_lifted
            PROVIDER cpu_tail_${first}_provider ${mix3} IMPORT_ARGUMENTS 3 RETURN_BYTES 8
            SECOND_PROVIDER cpu_slot_${second}_provider SECOND_SYMBOL fold4 SECOND_IMPORT_ARGUMENTS 4
            SECOND_RETURN_BYTES 2)
        list(APPEND slot_files "$<TARGET_FILE:cpu_slots_${variant}>" "$<TARGET_FILE:cpu_slots_${variant}_lifted>"
            "${CMAKE_CURRENT_BINARY_DIR}/cpu_slots_${variant}_lifted.cpp" "$<TARGET_FILE:cpu_tail_${first}_provider>"
            "$<TARGET_FILE:cpu_slot_${second}_provider>")
    endforeach()
    add_test(NAME cpu_aot_two_slots COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/two_slots_check.py" "$<TARGET_FILE:cpu_register_probe>" ${slot_files})

    foreach(variant IN ITEMS original swapped)
        cpu_asm_fixture(cpu_float_${variant} scalar_float)
        cpu_translation(cpu_float_${variant} cpu_sse_aot
            "blend_ss=f:ffqf,blend_sd=d:ddqd,convert=q:fdq,from_int=d:qq,classify_ss=q:ff,classify_sd=q:dq,round_trip=f:f,zero_xorps=d:d,zero_pxor=d:d,zero_xorpd=d:d,probe_ss=q:qff,neg_jcc=q:q,setcc_mix=q:qqq,cmovcc_mix=q:qqq,min_ss=f:ffq,max_ss=f:ffq,min_sd=d:ddq,max_sd=d:ddq,root_ss=f:fq,root_sd=d:dq,root_const_ss=f:,root_const_sd=d:,round_cvt=q:fdq,movq_gpr=q:dq")
        add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/cpu_float_${variant}_lifted.cpp" APPEND
            DEPENDS tools/cpu_switch_aot.py)
    endforeach()
    target_compile_definitions(cpu_float_swapped PRIVATE SWAP_OPERANDS)
    add_test(NAME cpu_aot_scalar_float COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/scalar_float_check.py"
        "$<TARGET_FILE:cpu_float_original>" "$<TARGET_FILE:cpu_float_original_lifted>"
        "$<TARGET_FILE:cpu_float_swapped>" "$<TARGET_FILE:cpu_float_swapped_lifted>" "$<TARGET_FILE:cpu_mxcsr_harness>")
    set(cpu_fma3_exports
        "op_vfmadd132ps_xmm,op_vfmadd132ps_ymm,op_vfmadd132pd_xmm,op_vfmadd132pd_ymm,op_vfmadd132ss,op_vfmadd132sd,"
        "op_vfmadd213ps_xmm,op_vfmadd213ps_ymm,op_vfmadd213pd_xmm,op_vfmadd213pd_ymm,op_vfmadd213ss,op_vfmadd213sd,"
        "op_vfmadd231ps_xmm,op_vfmadd231ps_ymm,op_vfmadd231pd_xmm,op_vfmadd231pd_ymm,op_vfmadd231ss,op_vfmadd231sd,"
        "op_vfmsub132ps_xmm,op_vfmsub132ps_ymm,op_vfmsub132pd_xmm,op_vfmsub132pd_ymm,op_vfmsub132ss,op_vfmsub132sd,"
        "op_vfmsub213ps_xmm,op_vfmsub213ps_ymm,op_vfmsub213pd_xmm,op_vfmsub213pd_ymm,op_vfmsub213ss,op_vfmsub213sd,"
        "op_vfmsub231ps_xmm,op_vfmsub231ps_ymm,op_vfmsub231pd_xmm,op_vfmsub231pd_ymm,op_vfmsub231ss,op_vfmsub231sd,"
        "op_vfnmadd132ps_xmm,op_vfnmadd132ps_ymm,op_vfnmadd132pd_xmm,op_vfnmadd132pd_ymm,op_vfnmadd132ss,op_vfnmadd132sd,"
        "op_vfnmadd213ps_xmm,op_vfnmadd213ps_ymm,op_vfnmadd213pd_xmm,op_vfnmadd213pd_ymm,op_vfnmadd213ss,op_vfnmadd213sd,"
        "op_vfnmadd231ps_xmm,op_vfnmadd231ps_ymm,op_vfnmadd231pd_xmm,op_vfnmadd231pd_ymm,op_vfnmadd231ss,op_vfnmadd231sd,"
        "op_vfnmsub132ps_xmm,op_vfnmsub132ps_ymm,op_vfnmsub132pd_xmm,op_vfnmsub132pd_ymm,op_vfnmsub132ss,op_vfnmsub132sd,"
        "op_vfnmsub213ps_xmm,op_vfnmsub213ps_ymm,op_vfnmsub213pd_xmm,op_vfnmsub213pd_ymm,op_vfnmsub213ss,op_vfnmsub213sd,"
        "op_vfnmsub231ps_xmm,op_vfnmsub231ps_ymm,op_vfnmsub231pd_xmm,op_vfnmsub231pd_ymm,op_vfnmsub231ss,op_vfnmsub231sd,"
        "op_vfmaddsub132ps_xmm,op_vfmaddsub132ps_ymm,op_vfmaddsub132pd_xmm,op_vfmaddsub132pd_ymm,"
        "op_vfmaddsub213ps_xmm,op_vfmaddsub213ps_ymm,op_vfmaddsub213pd_xmm,op_vfmaddsub213pd_ymm,"
        "op_vfmaddsub231ps_xmm,op_vfmaddsub231ps_ymm,op_vfmaddsub231pd_xmm,op_vfmaddsub231pd_ymm,"
        "op_vfmsubadd132ps_xmm,op_vfmsubadd132ps_ymm,op_vfmsubadd132pd_xmm,op_vfmsubadd132pd_ymm,"
        "op_vfmsubadd213ps_xmm,op_vfmsubadd213ps_ymm,op_vfmsubadd213pd_xmm,op_vfmsubadd213pd_ymm,"
        "op_vfmsubadd231ps_xmm,op_vfmsubadd231ps_ymm,op_vfmsubadd231pd_xmm,op_vfmsubadd231pd_ymm,"
        "op_mem_vfmadd132ss,op_mem_vfmsub213sd,op_mem_vfnmadd231ps_xmm,op_mem_vfnmsub132ps_ymm,"
        "op_mem_vfmaddsub213pd_xmm,op_mem_vfmsubadd231pd_ymm")
    string(CONCAT cpu_fma3_exports ${cpu_fma3_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_fma3_leaf_${variant} fma3_leaf)
        cpu_translation(cpu_fma3_leaf_${variant} cpu_avx2_aot "${cpu_fma3_exports}")
    endforeach()
    target_compile_definitions(cpu_fma3_leaf_altered PRIVATE ALTER_FMA)
    add_test(NAME cpu_aot_fma3 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/fma3_leaf_check.py"
        "$<TARGET_FILE:cpu_fma3_leaf_original>"
        "$<TARGET_FILE:cpu_fma3_leaf_original_lifted>"
        "$<TARGET_FILE:cpu_fma3_leaf_altered_lifted>"
        "$<TARGET_FILE:cpu_fma_packed_lifted>")
    set_tests_properties(cpu_aot_fma3 PROPERTIES SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_chained chained)
    cpu_translation(cpu_chained cpu_chained_aot choose_value)
    cpu_asm_fixture(cpu_chained_jne chained)
    target_compile_definitions(cpu_chained_jne PRIVATE USE_JNE)
    cpu_translation(cpu_chained_jne cpu_chained_aot choose_value)
    cpu_asm_fixture(cpu_chained_zero chained)
    target_compile_definitions(cpu_chained_zero PRIVATE USE_XOR_ZERO)
    cpu_translation(cpu_chained_zero cpu_chained_aot choose_value)
    cpu_asm_fixture(cpu_chained_imm chained)
    target_compile_definitions(cpu_chained_imm PRIVATE USE_IMM_REG)
    cpu_translation(cpu_chained_imm cpu_chained_aot choose_value)
    cpu_asm_fixture(cpu_chained_frame chained)
    target_compile_definitions(cpu_chained_frame PRIVATE USE_LARGE_FRAME)
    cpu_translation(cpu_chained_frame cpu_chained_aot choose_value)
    # One translation per export (the translator lifts one entry), each also built with /O2, where the
    # compiler removes a read that the generated C++ lets it remove.
    cpu_asm_fixture(cpu_chained_dead_read chained_dead_read)
    set(chained_dead_read_files)
    foreach(entry IN ITEMS read_dead disp_dead pair_dead read_skip read_live)
        set(name cpu_chained_dead_read_${entry})
        cpu_translation(cpu_chained_dead_read cpu_chained_aot ${entry} NAME ${name})
        set(optimized "${CMAKE_CURRENT_BINARY_DIR}/${name}_o2.dll")
        add_custom_command(OUTPUT "${optimized}"
            COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${CMAKE_CURRENT_BINARY_DIR}/${name}.cpp"
                "/Fo${CMAKE_CURRENT_BINARY_DIR}/${name}_o2.obj" "/Fe${optimized}"
            DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/${name}.cpp" VERBATIM)
        add_custom_target(${name}_o2 ALL DEPENDS "${optimized}")
        list(APPEND chained_dead_read_files "${entry}=$<TARGET_FILE:${name}>" "${entry}=${optimized}")
    endforeach()
    cpu_asm_fixture(cpu_callback callback)
    cpu_asm_fixture(cpu_version_query version_query)
    cpu_asm_fixture(cpu_heap_layout heap_layout)
    # Attribute words at xmem call sites, read from a source-built image (tools/xmem_attribute_scan.py).
    cpu_asm_fixture(cpu_xmem_attributes xmem_attributes)
    target_link_libraries(cpu_xmem_attributes PRIVATE xmem_shim)
    cpu_asm_fixture(cpu_xmem_delay xmem_delay)
    target_link_libraries(cpu_xmem_delay PRIVATE xmem_shim)
    target_link_options(cpu_xmem_delay PRIVATE /DELAYLOAD:xmem.dll)
    add_test(NAME xmem_attribute_scan COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_attribute_scan_check.py" "$<TARGET_FILE:cpu_xmem_attributes>"
        "$<TARGET_FILE:cpu_xmem_delay>")
    add_test(NAME xmem_attribute_scan_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xmem_attribute_scan_cli_check.py")

    # VEX.128 16-bit packed-integer leaf functions, an arithmetic-shift control, and their C++.
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_vex_words_${variant} vex_words)
        set(vex_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_words_${variant}_lifted.cpp")
        add_custom_command(OUTPUT "${vex_lifted}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_vex_aot.py"
                "$<TARGET_FILE:cpu_vex_words_${variant}>" "${vex_lifted}" widen_mix word_ops shift_edges
                store_reload aligned_ops byte_pack_reload sat_words mul_minmax_words cmp_words
                sraw_count_reg sraw_count_mem sllw_count_reg sllw_count_mem srlw_count_reg srlw_count_mem
            DEPENDS cpu_vex_words_${variant} tools/cpu_vex_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        add_library(cpu_vex_words_${variant}_lifted SHARED "${vex_lifted}")
    endforeach()
    target_compile_definitions(cpu_vex_words_altered PRIVATE LOGICAL_SHIFT)
    add_test(NAME cpu_aot_vex_words COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/vex_words_check.py"
        "$<TARGET_FILE:cpu_vex_words_original>" "$<TARGET_FILE:cpu_vex_words_original_lifted>"
        "$<TARGET_FILE:cpu_vex_words_altered>" "$<TARGET_FILE:cpu_vex_words_altered_lifted>")
    set_tests_properties(cpu_aot_vex_words PROPERTIES SKIP_RETURN_CODE 77)
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_vex_words_ext_${variant} vex_words_ext)
        set(vex_ext_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_words_ext_${variant}_lifted.cpp")
        add_custom_command(OUTPUT "${vex_ext_lifted}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_vex_aot.py"
                "$<TARGET_FILE:cpu_vex_words_ext_${variant}>" "${vex_ext_lifted}"
                pabsw_reg pabsw_mem signw_reg signw_mem mulhrsw_reg mulhrsw_mem
                phaddw_reg phaddw_mem ext_mem_r8_chain ext_aligned
            DEPENDS cpu_vex_words_ext_${variant} tools/cpu_vex_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        add_library(cpu_vex_words_ext_${variant}_lifted SHARED "${vex_ext_lifted}")
    endforeach()
    target_compile_definitions(cpu_vex_words_ext_altered PRIVATE ALTER_EXT)
    add_test(NAME cpu_aot_vex_words_ext COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/vex_words_ext_check.py"
        "$<TARGET_FILE:cpu_vex_words_ext_original>" "$<TARGET_FILE:cpu_vex_words_ext_original_lifted>"
        "$<TARGET_FILE:cpu_vex_words_ext_altered>" "$<TARGET_FILE:cpu_vex_words_ext_altered_lifted>")
    set_tests_properties(cpu_aot_vex_words_ext PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_vex_words_ext.txt")
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_vex_bytes_${variant} vex_bytes)
        set(vex_bytes_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_bytes_${variant}_lifted.cpp")
        add_custom_command(OUTPUT "${vex_bytes_lifted}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_vex_aot.py"
                "$<TARGET_FILE:cpu_vex_bytes_${variant}>" "${vex_bytes_lifted}"
                pandn_reg pandn_mem pavgb_reg pavgb_mem pmaddubsw_reg pmaddubsw_mem
                pshufb_reg pshufb_mem bytes_mem_r8_chain bytes_aligned
            DEPENDS cpu_vex_bytes_${variant} tools/cpu_vex_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        add_library(cpu_vex_bytes_${variant}_lifted SHARED "${vex_bytes_lifted}")
    endforeach()
    target_compile_definitions(cpu_vex_bytes_altered PRIVATE ALTER_BYTES)
    add_test(NAME cpu_aot_vex_bytes COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/vex_bytes_check.py"
        "$<TARGET_FILE:cpu_vex_bytes_original>" "$<TARGET_FILE:cpu_vex_bytes_original_lifted>"
        "$<TARGET_FILE:cpu_vex_bytes_altered>" "$<TARGET_FILE:cpu_vex_bytes_altered_lifted>")
    set_tests_properties(cpu_aot_vex_bytes PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_vex_bytes.txt")
    # cpu_aot_vex_bytes_arith
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_vex_bytes_arith_${variant} vex_bytes_arith)
        set(vex_bytes_arith_lifted "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_bytes_arith_${variant}_lifted.cpp")
        add_custom_command(OUTPUT "${vex_bytes_arith_lifted}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_vex_aot.py"
                "$<TARGET_FILE:cpu_vex_bytes_arith_${variant}>" "${vex_bytes_arith_lifted}"
                paddb_reg paddb_mem psubb_reg psubb_mem psubb_self
                pcmpeqb_reg pcmpeqb_mem pcmpgtb_reg pcmpgtb_mem
                bytes_arith_mem_r8_chain bytes_arith_aligned
            DEPENDS cpu_vex_bytes_arith_${variant} tools/cpu_vex_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        add_library(cpu_vex_bytes_arith_${variant}_lifted SHARED "${vex_bytes_arith_lifted}")
    endforeach()
    target_compile_definitions(cpu_vex_bytes_arith_altered PRIVATE ALTER_BYTE_ARITH)
    add_test(NAME cpu_aot_vex_bytes_arith COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/vex_bytes_arith_check.py"
        "$<TARGET_FILE:cpu_vex_bytes_arith_original>" "$<TARGET_FILE:cpu_vex_bytes_arith_original_lifted>"
        "$<TARGET_FILE:cpu_vex_bytes_arith_altered>" "$<TARGET_FILE:cpu_vex_bytes_arith_altered_lifted>")
    set_tests_properties(cpu_aot_vex_bytes_arith PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_vex_bytes_arith.txt")
    set(cpu_seg_inspect_exports
        "lar_reg16,lar_reg32,lar_reg64,lar_mem16,lar_mem32_disp,lar_mem64_disp,"
        "lsl_reg16,lsl_reg32,lsl_reg64,lsl_mem16,lsl_mem32_disp,lsl_mem64_disp,"
        "verr_reg,verw_reg,verr_mem_disp,verw_mem_disp,"
        "seg_imm_select,seg_flags_preserve,seg_cmov32,seg_discarded_read")
    string(CONCAT cpu_seg_inspect_exports ${cpu_seg_inspect_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_seg_inspect_${variant} seg_inspect)
        cpu_translation(cpu_seg_inspect_${variant} cpu_seg_inspect_aot "${cpu_seg_inspect_exports}")
    endforeach()
    target_compile_definitions(cpu_seg_inspect_altered PRIVATE ALTER_IMM)
    add_test(NAME cpu_aot_seg_inspect COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/seg_inspect_check.py"
        "$<TARGET_FILE:cpu_seg_inspect_original>"
        "$<TARGET_FILE:cpu_seg_inspect_original_lifted>"
        "$<TARGET_FILE:cpu_seg_inspect_altered>"
        "$<TARGET_FILE:cpu_seg_inspect_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_seg_inspect PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_seg_inspect.txt")
    cpu_asm_fixture(cpu_bink_heap bink_heap)
    add_library(cpu_bink_heap_provider SHARED tests/cpu/bink_heap_provider.cpp src/era_heap.cpp)
    target_include_directories(cpu_bink_heap_provider PRIVATE src)
    target_link_libraries(cpu_bink_heap PRIVATE cpu_bink_heap_provider)
    function(bink_heap_translation target image dependency)
        set(cpp "${CMAKE_CURRENT_BINARY_DIR}/${target}.cpp")
        add_custom_command(OUTPUT "${cpp}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/bink_heap_aot.py"
                "${image}" "${cpp}" ${ARGN}
            DEPENDS ${dependency} tools/bink_heap_aot.py tools/ffx_version_query.py
                tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
        add_library(${target} SHARED "${cpp}")
        target_link_libraries(${target} PRIVATE cpu_bink_heap_provider)
    endfunction()
    bink_heap_translation(cpu_bink_heap_lifted "$<TARGET_FILE:cpu_bink_heap>" cpu_bink_heap --group-entry heap_group)
    add_test(NAME cpu_aot_bink_heap COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bink_heap_check.py" "$<TARGET_FILE:cpu_bink_heap_provider>"
        "$<TARGET_FILE:cpu_bink_heap>" "$<TARGET_FILE:cpu_bink_heap_lifted>")
    add_test(NAME cpu_aot_bink_group COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bink_group_check.py" "$<TARGET_FILE:cpu_bink_heap_provider>"
        "$<TARGET_FILE:cpu_bink_heap>" "$<TARGET_FILE:cpu_bink_heap_lifted>")
    set(BINK_GROUP_ENTRY "" CACHE STRING "Optional grouped allocation caller RVA in the local Bink image")
    set(BINK_HEAP_IMAGE "" CACHE FILEPATH "Local PE containing the Bink allocation and release callers")
    set(BINK_HEAP_ENTRIES "" CACHE STRING "Two semicolon-separated entry RVAs (allocation;release)")
    if(BINK_HEAP_IMAGE)
        list(LENGTH BINK_HEAP_ENTRIES entry_count)
        if(NOT entry_count EQUAL 2)
            message(FATAL_ERROR "Provide both BINK_HEAP_ENTRIES for the selected local image")
        endif()
        set(group_args)
        if(BINK_GROUP_ENTRY)
            set(group_args --group-entry "${BINK_GROUP_ENTRY}")
            add_test(NAME cpu_aot_bink_package_group COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/cpu/bink_group_check.py" "$<TARGET_FILE:cpu_bink_heap_provider>"
                "$<TARGET_FILE:cpu_bink_package_lifted>")
        endif()
        bink_heap_translation(cpu_bink_package_lifted "${BINK_HEAP_IMAGE}" "${BINK_HEAP_IMAGE}"
            --entries ${BINK_HEAP_ENTRIES} ${group_args})
        add_test(NAME cpu_aot_bink_package_heap COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/bink_heap_check.py" "$<TARGET_FILE:cpu_bink_heap_provider>"
            "$<TARGET_FILE:cpu_bink_package_lifted>")
    endif()
    cpu_asm_fixture(cpu_working_set_delta working_set_delta)
    function(working_set_delta_translation target image dependency)
        set(cpp "${CMAKE_CURRENT_BINARY_DIR}/${target}.cpp")
        add_custom_command(OUTPUT "${cpp}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/ffx_working_set_delta.py"
                "${image}" "${cpp}" ${ARGN}
            DEPENDS ${dependency} tools/ffx_working_set_delta.py tools/ffx_version_query.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(${target} SHARED "${cpp}")
    endfunction()
    working_set_delta_translation(cpu_working_set_delta_lifted "$<TARGET_FILE:cpu_working_set_delta>" cpu_working_set_delta)
    add_test(NAME cpu_working_set_delta COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/working_set_delta_check.py" "$<TARGET_FILE:cpu_working_set_delta>"
        "$<TARGET_FILE:cpu_working_set_delta_lifted>")
    if(FFX_UPSCALER_IMAGE)
        working_set_delta_translation(ffx_package_working_set_delta "${FFX_UPSCALER_IMAGE}" "${FFX_UPSCALER_IMAGE}" --package)
        add_test(NAME ffx_package_working_set_delta COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/working_set_delta_check.py" "$<TARGET_FILE:ffx_package_working_set_delta>")
        # The same translated updates fed with desktop xmem.dll samples around a real D3D12 heap.
        add_executable(ffx_package_working_set_xmem tests/cpu/working_set_xmem_check.cpp)
        target_link_libraries(ffx_package_working_set_xmem PRIVATE ffx_package_working_set_delta xmem_shim d3d12 dxgi)
        target_compile_features(ffx_package_working_set_xmem PRIVATE cxx_std_17)
        foreach(adapter IN ITEMS warp hardware)
            add_test(NAME ffx_package_working_set_xmem_${adapter} COMMAND ffx_package_working_set_xmem ${adapter})
            set_tests_properties(ffx_package_working_set_xmem_${adapter} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
        endforeach()
    endif()
    cpu_asm_fixture(cpu_bink_descriptors bink_descriptors)
    function(bink_descriptors_translation target image dependency)
        set(cpp "${CMAKE_CURRENT_BINARY_DIR}/${target}.cpp")
        add_custom_command(OUTPUT "${cpp}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/bink_descriptors_aot.py"
                "${image}" "${cpp}" --frame-planes ${ARGN}
            DEPENDS ${dependency} tools/bink_descriptors_aot.py tools/bink_heap_aot.py
                tools/ffx_version_query.py tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(${target} SHARED "${cpp}")
    endfunction()
    bink_descriptors_translation(cpu_bink_descriptors_lifted "$<TARGET_FILE:cpu_bink_descriptors>" cpu_bink_descriptors)
    add_test(NAME cpu_bink_descriptors COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bink_descriptors_check.py" --native "$<TARGET_FILE:cpu_bink_descriptors>"
        "$<TARGET_FILE:cpu_bink_descriptors_lifted>")
    add_test(NAME cpu_bink_frame_planes COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bink_frame_planes_check.py" "$<TARGET_FILE:cpu_bink_descriptors>"
        "$<TARGET_FILE:cpu_bink_descriptors_lifted>")
    set(BINK_DESCRIPTOR_IMAGE "" CACHE FILEPATH "Local Bink DLL for the grouped descriptor producer experiment")
    if(BINK_DESCRIPTOR_IMAGE)
        bink_descriptors_translation(cpu_bink_package_descriptors "${BINK_DESCRIPTOR_IMAGE}" "${BINK_DESCRIPTOR_IMAGE}" --package)
        add_test(NAME cpu_bink_package_frame_planes COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/bink_frame_planes_check.py" "$<TARGET_FILE:cpu_bink_package_descriptors>")
        add_test(NAME cpu_bink_package_descriptors COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/bink_descriptors_check.py" "$<TARGET_FILE:cpu_bink_package_descriptors>")
    endif()
    function(bink_frame_integration name driver descriptors heap)
        # Link identical translated objects to the shared DLL and to the recording
        # provider so a failing allocation can be injected at the import boundary.
        add_library(${name}_objects OBJECT "${driver}" "${CMAKE_CURRENT_BINARY_DIR}/${descriptors}.cpp"
            "${CMAKE_CURRENT_BINARY_DIR}/${heap}.cpp")
        add_library(${name} SHARED $<TARGET_OBJECTS:${name}_objects>)
        target_link_libraries(${name} PRIVATE xmem_shim)
        add_library(${name}_observed SHARED $<TARGET_OBJECTS:${name}_objects>)
        target_link_libraries(${name}_observed PRIVATE cpu_bink_heap_provider)
        add_test(NAME ${name} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/bink_frame_heap_check.py" "$<TARGET_FILE:${name}>"
            "$<TARGET_FILE:${name}_observed>" "$<TARGET_FILE:xmem_shim>" "$<TARGET_FILE:cpu_bink_heap_provider>")
    endfunction()
    bink_frame_integration(cpu_bink_frame_to_heap tests/cpu/bink_frame_control.cpp
        cpu_bink_descriptors_lifted cpu_bink_heap_lifted)
    if(BINK_DESCRIPTOR_IMAGE AND BINK_DESCRIPTOR_IMAGE STREQUAL BINK_HEAP_IMAGE AND BINK_GROUP_ENTRY)
        set(frame_driver "${CMAKE_CURRENT_BINARY_DIR}/bink_frame_driver.cpp")
        add_custom_command(OUTPUT "${frame_driver}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/bink_frame_aot.py"
                "${BINK_DESCRIPTOR_IMAGE}" "${frame_driver}"
            DEPENDS "${BINK_DESCRIPTOR_IMAGE}" tools/bink_frame_aot.py tools/bink_descriptors_aot.py
                tools/bink_heap_aot.py tools/ffx_version_query.py tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        bink_frame_integration(cpu_bink_package_frame_to_heap "${frame_driver}"
            cpu_bink_package_descriptors cpu_bink_package_lifted)
    endif()
    set(heap_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_heap_layout_lifted.cpp")
    add_custom_command(OUTPUT "${heap_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/heap_layout.py"
            emit "$<TARGET_FILE:cpu_heap_layout>" "${heap_fixture}"
        DEPENDS cpu_heap_layout tests/cpu/heap_layout.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_heap_layout_lifted SHARED "${heap_fixture}")
    add_test(NAME cpu_aot_heap_layout COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/heap_layout.py"
        check "$<TARGET_FILE:cpu_heap_layout>" "$<TARGET_FILE:cpu_heap_layout_lifted>")
    cpu_asm_fixture(cpu_rcx_branches rcx_branches)
    # The lifted DLL and three mutated controls that the check requires to mismatch.
    foreach(variant IN ITEMS lifted noecx nozf jrcxz)
        set(rcx_branches_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_rcx_branches_${variant}.cpp")
        add_custom_command(OUTPUT "${rcx_branches_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rcx_branches.py"
                emit "$<TARGET_FILE:cpu_rcx_branches>" "${rcx_branches_fixture}" ${variant}
            DEPENDS cpu_rcx_branches tests/cpu/rcx_branches.py tools/ffx_version_query.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_rcx_branches_${variant} SHARED "${rcx_branches_fixture}")
    endforeach()
    add_test(NAME cpu_aot_rcx_branches COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rcx_branches.py"
        check "$<TARGET_FILE:cpu_rcx_branches>" "$<TARGET_FILE:cpu_rcx_branches_lifted>"
        "$<TARGET_FILE:cpu_rcx_branches_noecx>" "$<TARGET_FILE:cpu_rcx_branches_nozf>"
        "$<TARGET_FILE:cpu_rcx_branches_jrcxz>")
    cpu_asm_fixture(cpu_shift_count shift_count)
    set(shift_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_shift_count_lifted.cpp")
    add_custom_command(OUTPUT "${shift_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/shift_count.py"
            emit "$<TARGET_FILE:cpu_shift_count>" "${shift_fixture}"
        DEPENDS cpu_shift_count tests/cpu/shift_count.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_shift_count_lifted SHARED "${shift_fixture}")
    add_test(NAME cpu_aot_shift_count COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/shift_count.py"
        check "$<TARGET_FILE:cpu_shift_count>" "$<TARGET_FILE:cpu_shift_count_lifted>")
    cpu_asm_fixture(cpu_carry_rotates carry_rotates)
    # The lifted DLL and three mutated controls that the check requires to mismatch.
    foreach(variant IN ITEMS lifted nomask nocarry stc)
        set(carry_rotates_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_carry_rotates_${variant}.cpp")
        add_custom_command(OUTPUT "${carry_rotates_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/carry_rotates.py"
                emit "$<TARGET_FILE:cpu_carry_rotates>" "${carry_rotates_fixture}" ${variant}
            DEPENDS cpu_carry_rotates tests/cpu/carry_rotates.py tools/ffx_version_query.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_carry_rotates_${variant} SHARED "${carry_rotates_fixture}")
    endforeach()
    add_test(NAME cpu_aot_carry_rotates COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/carry_rotates.py"
        check "$<TARGET_FILE:cpu_carry_rotates>" "$<TARGET_FILE:cpu_carry_rotates_lifted>"
        "$<TARGET_FILE:cpu_carry_rotates_nomask>" "$<TARGET_FILE:cpu_carry_rotates_nocarry>"
        "$<TARGET_FILE:cpu_carry_rotates_stc>")
    set(query_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_version_query_lifted.cpp")
    add_custom_command(OUTPUT "${query_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/version_query_fixture.py"
            emit "$<TARGET_FILE:cpu_version_query>" "${query_fixture}"
        DEPENDS cpu_version_query tests/cpu/version_query_fixture.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py tests/cpu/version_query_check.py VERBATIM)
    add_library(cpu_version_query_lifted SHARED "${query_fixture}")
    add_test(NAME cpu_aot_version_query COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/version_query_fixture.py" check "$<TARGET_FILE:cpu_version_query>"
        "$<TARGET_FILE:cpu_version_query_lifted>")
    add_test(NAME cpu_lower_prefixes COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/lower_prefixes_check.py")
    cpu_asm_fixture(cpu_xchg xchg)
    # The lifted DLL and two mutated controls that the check requires to mismatch.
    foreach(variant IN ITEMS lifted plain oneway)
        set(xchg_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_xchg_${variant}.cpp")
        add_custom_command(OUTPUT "${xchg_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/xchg.py"
                emit "$<TARGET_FILE:cpu_xchg>" "${xchg_fixture}" ${variant}
            DEPENDS cpu_xchg tests/cpu/xchg.py tools/ffx_version_query.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_xchg_${variant} SHARED "${xchg_fixture}")
    endforeach()
    x2w_add_check_part(cpu_aot_xchg native "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/xchg.py"
        check-native "$<TARGET_FILE:cpu_xchg>")
    x2w_add_check_part(cpu_aot_xchg lifted "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/xchg.py"
        check-lifted "$<TARGET_FILE:cpu_xchg_lifted>")
    x2w_add_check_part(cpu_aot_xchg controls "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/xchg.py"
        check-controls "$<TARGET_FILE:cpu_xchg_plain>" "$<TARGET_FILE:cpu_xchg_oneway>")
    add_test(NAME cpu_aot_xchg COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/xchg.py"
        check-rejections)
    x2w_require_check_parts(cpu_aot_xchg native lifted controls)
    cpu_asm_fixture(cpu_address_size address_size)
    set(address_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_address_size_lifted.cpp")
    add_custom_command(OUTPUT "${address_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/address_size.py"
            emit "$<TARGET_FILE:cpu_address_size>" "${address_fixture}"
        DEPENDS cpu_address_size tests/cpu/address_size.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_address_size_lifted SHARED "${address_fixture}")
    add_test(NAME cpu_aot_address_size COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/address_size.py"
        check "$<TARGET_FILE:cpu_address_size>" "$<TARGET_FILE:cpu_address_size_lifted>")
    cpu_asm_fixture(cpu_movbe movbe)
    # The lifted DLL and three mutated controls that the check requires to mismatch.
    foreach(variant IN ITEMS lifted noswap clear16 flags)
        set(movbe_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_movbe_${variant}.cpp")
        add_custom_command(OUTPUT "${movbe_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/movbe.py"
                emit "$<TARGET_FILE:cpu_movbe>" "${movbe_fixture}" ${variant}
            DEPENDS cpu_movbe tests/cpu/movbe.py tools/ffx_version_query.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_movbe_${variant} SHARED "${movbe_fixture}")
    endforeach()
    add_test(NAME cpu_aot_movbe COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/movbe.py"
        check "$<TARGET_FILE:cpu_movbe>" "$<TARGET_FILE:cpu_movbe_lifted>"
        "$<TARGET_FILE:cpu_movbe_noswap>" "$<TARGET_FILE:cpu_movbe_clear16>" "$<TARGET_FILE:cpu_movbe_flags>")
    set_tests_properties(cpu_aot_movbe PROPERTIES SKIP_RETURN_CODE 77)

    # cpu_aot_movbe_dedicated
    set(cpu_movbe_aot_exports
        "op_movbe_load16,op_movbe_load16_disp,op_movbe_load32,op_movbe_load32_disp,"
        "op_movbe_load64,op_movbe_load64_disp,"
        "op_movbe_store16,op_movbe_store16_disp,op_movbe_store32,op_movbe_store32_disp,"
        "op_movbe_store64,op_movbe_store64_disp,"
        "op_movbe_flags_cf_zf_of_pf,op_movbe_flags_sf_of_pf,op_movbe_flags_all_clear,"
        "op_r8_source_then_store,op_movbe_discarded_read")
    string(CONCAT cpu_movbe_aot_exports ${cpu_movbe_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_movbe_aot_${variant} movbe_aot)
        cpu_translation(cpu_movbe_aot_${variant} cpu_movbe_aot "${cpu_movbe_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_movbe_aot_altered PRIVATE ALTER_MOVBE)
    add_test(NAME cpu_aot_movbe_dedicated COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/movbe_aot_check.py"
        "$<TARGET_FILE:cpu_movbe_aot_original>"
        "$<TARGET_FILE:cpu_movbe_aot_original_lifted>"
        "$<TARGET_FILE:cpu_movbe_aot_altered>"
        "$<TARGET_FILE:cpu_movbe_aot_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_movbe_dedicated PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_movbe_dedicated.txt")
    cpu_asm_fixture(cpu_bmi1 bmi1)
    set(bmi1_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_bmi1_lifted.cpp")
    add_custom_command(OUTPUT "${bmi1_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/bmi1.py"
            emit "$<TARGET_FILE:cpu_bmi1>" "${bmi1_fixture}"
        DEPENDS cpu_bmi1 tests/cpu/bmi1.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_bmi1_lifted SHARED "${bmi1_fixture}")
    add_test(NAME cpu_aot_bmi1 COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/bmi1.py"
        check "$<TARGET_FILE:cpu_bmi1>" "$<TARGET_FILE:cpu_bmi1_lifted>")
    set_tests_properties(cpu_aot_bmi1 PROPERTIES SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_bit_ops bit_ops)
    set(bit_ops_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_bit_ops_lifted.cpp")
    add_custom_command(OUTPUT "${bit_ops_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/bit_ops.py"
            emit "$<TARGET_FILE:cpu_bit_ops>" "${bit_ops_fixture}"
        DEPENDS cpu_bit_ops tests/cpu/bit_ops.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_bit_ops_lifted SHARED "${bit_ops_fixture}")
    add_test(NAME cpu_aot_bit_ops COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/bit_ops.py"
        check "$<TARGET_FILE:cpu_bit_ops>" "$<TARGET_FILE:cpu_bit_ops_lifted>")
    set_tests_properties(cpu_aot_bit_ops PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_rotates_shifts rotates_shifts)
    set(rotates_shifts_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_rotates_shifts_lifted.cpp")
    add_custom_command(OUTPUT "${rotates_shifts_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rotates_shifts.py"
            emit "$<TARGET_FILE:cpu_rotates_shifts>" "${rotates_shifts_fixture}"
        DEPENDS cpu_rotates_shifts tests/cpu/rotates_shifts.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_rotates_shifts_lifted SHARED "${rotates_shifts_fixture}")
    add_test(NAME cpu_aot_rotates_shifts COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rotates_shifts.py"
        check "$<TARGET_FILE:cpu_rotates_shifts>" "$<TARGET_FILE:cpu_rotates_shifts_lifted>")
    cpu_asm_fixture(cpu_string_ops string_ops)
    # The lifted DLL and three mutated controls that the check requires to mismatch.
    foreach(variant IN ITEMS lifted memmove swapped forward)
        set(string_ops_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_string_ops_${variant}.cpp")
        add_custom_command(OUTPUT "${string_ops_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/string_ops.py"
                emit "$<TARGET_FILE:cpu_string_ops>" "${string_ops_fixture}" ${variant}
            DEPENDS cpu_string_ops tests/cpu/string_ops.py tools/ffx_version_query.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_string_ops_${variant} SHARED "${string_ops_fixture}")
    endforeach()
    add_test(NAME cpu_aot_string_ops COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/string_ops.py"
        check "$<TARGET_FILE:cpu_string_ops>" "$<TARGET_FILE:cpu_string_ops_lifted>"
        "$<TARGET_FILE:cpu_string_ops_memmove>" "$<TARGET_FILE:cpu_string_ops_swapped>"
        "$<TARGET_FILE:cpu_string_ops_forward>")
    cpu_asm_fixture(cpu_sign_ext_adc sign_ext_adc)
    set(sign_ext_adc_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sign_ext_adc_lifted.cpp")
    add_custom_command(OUTPUT "${sign_ext_adc_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sign_ext_adc.py"
            emit "$<TARGET_FILE:cpu_sign_ext_adc>" "${sign_ext_adc_fixture}"
        DEPENDS cpu_sign_ext_adc tests/cpu/sign_ext_adc.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sign_ext_adc_lifted SHARED "${sign_ext_adc_fixture}")
    add_test(NAME cpu_aot_sign_ext_adc COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sign_ext_adc.py"
        check "$<TARGET_FILE:cpu_sign_ext_adc>" "$<TARGET_FILE:cpu_sign_ext_adc_lifted>")

    cpu_asm_fixture(cpu_fences_hints fences_hints)
    set(fences_hints_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_fences_hints_lifted.cpp")
    add_custom_command(OUTPUT "${fences_hints_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/fences_hints.py"
            emit "$<TARGET_FILE:cpu_fences_hints>" "${fences_hints_fixture}"
        DEPENDS cpu_fences_hints tests/cpu/fences_hints.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_fences_hints_lifted SHARED "${fences_hints_fixture}")
    add_test(NAME cpu_aot_fences_hints COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/fences_hints.py"
        check "$<TARGET_FILE:cpu_fences_hints>" "$<TARGET_FILE:cpu_fences_hints_lifted>" baseline)
    foreach(capability IN ITEMS prefetch_amd clflush clflushopt clwb)
        add_test(NAME cpu_aot_fences_hints_${capability}
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/fences_hints.py"
            check "$<TARGET_FILE:cpu_fences_hints>" "$<TARGET_FILE:cpu_fences_hints_lifted>" "${capability}")
        set_tests_properties(cpu_aot_fences_hints_${capability} PROPERTIES SKIP_RETURN_CODE 77)
    endforeach()

    cpu_asm_fixture(cpu_bmi2 bmi2)
    set(bmi2_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_bmi2_lifted.cpp")
    add_custom_command(OUTPUT "${bmi2_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/bmi2.py"
            emit "$<TARGET_FILE:cpu_bmi2>" "${bmi2_fixture}"
        DEPENDS cpu_bmi2 tests/cpu/bmi2.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_bmi2_lifted SHARED "${bmi2_fixture}")
    add_test(NAME cpu_aot_bmi2 COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/bmi2.py"
        check "$<TARGET_FILE:cpu_bmi2>" "$<TARGET_FILE:cpu_bmi2_lifted>")
    set_tests_properties(cpu_aot_bmi2 PROPERTIES SKIP_RETURN_CODE 77)

    # cpu_aot_bmi2_shift
    set(cpu_bmi2_shift_exports
        "op_rorx32,op_rorx32_imm32,op_rorx32_imm37,op_rorx64,op_rorx64_imm64,op_rorx64_imm73,"
        "op_shlx32,op_shlx64,op_shrx32,op_shrx64,op_sarx32,op_sarx64,"
        "op_rorx32_mem,op_rorx64_mem,op_shlx32_mem,op_shlx64_mem,"
        "op_shrx32_mem,op_shrx64_mem,op_sarx32_mem,op_sarx64_mem,"
        "op_mem_r8_source,op_flags_preserve32,op_flags_preserve64,"
        "op_flags_preserve_mem,op_bmi2_discarded_read")
    string(CONCAT cpu_bmi2_shift_exports ${cpu_bmi2_shift_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_bmi2_shift_${variant} bmi2_shift)
        cpu_translation(cpu_bmi2_shift_${variant} cpu_bmi2_shift_aot "${cpu_bmi2_shift_exports}")
    endforeach()
    target_compile_definitions(cpu_bmi2_shift_altered PRIVATE ALTER_BMI2_SHIFT)
    add_test(NAME cpu_aot_bmi2_shift COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bmi2_shift_check.py"
        "$<TARGET_FILE:cpu_bmi2_shift_original>"
        "$<TARGET_FILE:cpu_bmi2_shift_original_lifted>"
        "$<TARGET_FILE:cpu_bmi2_shift_altered>"
        "$<TARGET_FILE:cpu_bmi2_shift_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_bmi2_shift PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_bmi2_shift.txt")

    # cpu_aot_bmi2_bit
    set(cpu_bmi2_bit_exports
        "op_bzhi32,op_bzhi64,op_mulx32,op_mulx64,op_mulx32_alias,op_mulx64_alias,"
        "op_pdep32,op_pdep64,op_pext32,op_pext64,"
        "op_bzhi32_mem,op_bzhi64_mem,op_mulx32_mem,op_mulx64_mem,"
        "op_pdep32_mem,op_pdep64_mem,op_pext32_mem,op_pext64_mem,"
        "op_mem_r8_source,op_bzhi32_flags,op_bzhi64_flags,"
        "op_flags_preserve32,op_flags_preserve64,op_flags_preserve_pf,"
        "op_flags_preserve_mem,op_bmi2_bit_discarded_read")
    string(CONCAT cpu_bmi2_bit_exports ${cpu_bmi2_bit_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_bmi2_bit_${variant} bmi2_bit_aot)
        cpu_translation(cpu_bmi2_bit_${variant} cpu_bmi2_bit_aot "${cpu_bmi2_bit_exports}")
    endforeach()
    target_compile_definitions(cpu_bmi2_bit_altered PRIVATE ALTER_BMI2_BIT)
    add_test(NAME cpu_aot_bmi2_bit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bmi2_bit_aot_check.py"
        "$<TARGET_FILE:cpu_bmi2_bit_original>"
        "$<TARGET_FILE:cpu_bmi2_bit_original_lifted>"
        "$<TARGET_FILE:cpu_bmi2_bit_altered>"
        "$<TARGET_FILE:cpu_bmi2_bit_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_bmi2_bit PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_bmi2_bit.txt")

    # cpu_aot_bmi1_bit
    set(cpu_bmi1_aot_exports
        "op_blsi32,op_blsi64,op_blsmsk32,op_blsmsk64,op_blsr32,op_blsr64,"
        "op_blsi32_mem,op_blsi64_mem,op_blsmsk32_mem,op_blsmsk64_mem,op_blsr32_mem,op_blsr64_mem,"
        "op_blsi32_flags,op_blsi64_flags,op_blsmsk32_flags,op_blsmsk64_flags,"
        "op_blsr32_flags,op_blsr64_flags,op_blsr64_mem_flags,"
        "op_r8_source_then_store,op_bmi1_discarded_read")
    string(CONCAT cpu_bmi1_aot_exports ${cpu_bmi1_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_bmi1_aot_${variant} bmi1_aot)
        cpu_translation(cpu_bmi1_aot_${variant} cpu_bmi1_aot "${cpu_bmi1_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_bmi1_aot_altered PRIVATE ALTER_BMI1)
    add_test(NAME cpu_aot_bmi1_bit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bmi1_aot_check.py"
        "$<TARGET_FILE:cpu_bmi1_aot_original>"
        "$<TARGET_FILE:cpu_bmi1_aot_original_lifted>"
        "$<TARGET_FILE:cpu_bmi1_aot_altered>"
        "$<TARGET_FILE:cpu_bmi1_aot_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_bmi1_bit PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_bmi1_bit.txt")

    # cpu_aot_bmi1_logic
    set(cpu_bmi1_logic_aot_exports
        "op_andn32,op_andn64,op_bextr32,op_bextr64,op_tzcnt32,op_tzcnt64,"
        "op_andn32_mem,op_andn64_mem,op_bextr32_mem,op_bextr64_mem,op_tzcnt32_mem,op_tzcnt64_mem,"
        "op_andn32_flags,op_andn64_flags,op_bextr32_flags,op_bextr64_flags,"
        "op_tzcnt32_flags,op_tzcnt64_flags,op_bextr64_mem_flags,op_tzcnt64_mem_flags,"
        "op_r8_source_then_store,op_dst_alias_src,op_bmi1_logic_discarded_read")
    string(CONCAT cpu_bmi1_logic_aot_exports ${cpu_bmi1_logic_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_bmi1_logic_aot_${variant} bmi1_logic_aot)
        cpu_translation(cpu_bmi1_logic_aot_${variant} cpu_bmi1_logic_aot "${cpu_bmi1_logic_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_bmi1_logic_aot_altered PRIVATE ALTER_BMI1_LOGIC)
    add_test(NAME cpu_aot_bmi1_logic COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/bmi1_logic_aot_check.py"
        "$<TARGET_FILE:cpu_bmi1_logic_aot_original>"
        "$<TARGET_FILE:cpu_bmi1_logic_aot_original_lifted>"
        "$<TARGET_FILE:cpu_bmi1_logic_aot_altered>"
        "$<TARGET_FILE:cpu_bmi1_logic_aot_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_bmi1_logic PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_bmi1_logic.txt")

    cpu_asm_fixture(cpu_sse2_packed_cvt sse2_packed_cvt)
    target_sources(cpu_sse2_packed_cvt PRIVATE tests/cpu/sse2_mxcsr_test.asm)
    set(sse2_packed_cvt_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse2_packed_cvt_lifted.cpp")
    add_custom_command(OUTPUT "${sse2_packed_cvt_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_packed_cvt.py"
            emit "$<TARGET_FILE:cpu_sse2_packed_cvt>" "${sse2_packed_cvt_fixture}"
        DEPENDS cpu_sse2_packed_cvt tests/cpu/sse2_packed_cvt.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse2_packed_cvt_lifted SHARED "${sse2_packed_cvt_fixture}")
    add_test(NAME cpu_aot_sse2_packed_cvt COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_packed_cvt.py"
        check "$<TARGET_FILE:cpu_sse2_packed_cvt>" "$<TARGET_FILE:cpu_sse2_packed_cvt_lifted>")
    cpu_asm_fixture(cpu_crypto_sha crypto_sha)
    set(crypto_sha_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_crypto_sha_lifted.cpp")
    add_custom_command(OUTPUT "${crypto_sha_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/crypto_sha.py"
            emit "$<TARGET_FILE:cpu_crypto_sha>" "${crypto_sha_fixture}"
        DEPENDS cpu_crypto_sha tests/cpu/crypto_sha.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_crypto_sha_lifted SHARED "${crypto_sha_fixture}")
    add_test(NAME cpu_aot_crypto_sha COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/crypto_sha.py"
        check "$<TARGET_FILE:cpu_crypto_sha>" "$<TARGET_FILE:cpu_crypto_sha_lifted>")
    set_tests_properties(cpu_aot_crypto_sha PROPERTIES SKIP_RETURN_CODE 77)

    set(cpu_sha1_aot_exports
        "op_sha1rnds4_0_reg,op_sha1rnds4_1_reg,op_sha1rnds4_2_reg,op_sha1rnds4_3_reg,"
        "op_sha1rnds4_hi_imm,op_sha1rnds4_0_mem,op_sha1rnds4_1_mem,op_sha1rnds4_2_mem,"
        "op_sha1rnds4_3_mem,op_sha1rnds4_self,"
        "op_sha1nexte_reg,op_sha1nexte_mem,op_sha1nexte_self,"
        "op_sha1msg1_reg,op_sha1msg1_mem,op_sha1msg1_self,"
        "op_sha1msg2_reg,op_sha1msg2_mem,op_sha1msg2_self,"
        "op_sha1_pipeline")
    string(CONCAT cpu_sha1_aot_exports ${cpu_sha1_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sha1_aot_${variant} sha1_aot)
        cpu_translation(cpu_sha1_aot_${variant} cpu_sha1_aot "${cpu_sha1_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_sha1_aot_altered PRIVATE ALTER_SHA1)
    add_test(NAME cpu_aot_sha1 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sha1_aot_check.py"
        "$<TARGET_FILE:cpu_sha1_aot_original>"
        "$<TARGET_FILE:cpu_sha1_aot_original_lifted>"
        "$<TARGET_FILE:cpu_sha1_aot_altered>"
        "$<TARGET_FILE:cpu_sha1_aot_altered_lifted>")
    set_tests_properties(cpu_aot_sha1 PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_sha1.txt")

    cpu_asm_fixture(cpu_mul_div mul_div)
    set(mul_div_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_mul_div_lifted.cpp")
    add_custom_command(OUTPUT "${mul_div_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/mul_div.py"
            emit "$<TARGET_FILE:cpu_mul_div>" "${mul_div_fixture}"
        DEPENDS cpu_mul_div tests/cpu/mul_div.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_mul_div_lifted SHARED "${mul_div_fixture}")
    add_test(NAME cpu_aot_mul_div COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/mul_div.py"
        check "$<TARGET_FILE:cpu_mul_div>" "$<TARGET_FILE:cpu_mul_div_lifted>")

    cpu_asm_fixture(cpu_cmpxchg_wide cmpxchg_wide)
    set(cmpxchg_wide_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_cmpxchg_wide_lifted.cpp")
    add_custom_command(OUTPUT "${cmpxchg_wide_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/cmpxchg_wide.py"
            emit "$<TARGET_FILE:cpu_cmpxchg_wide>" "${cmpxchg_wide_fixture}"
        DEPENDS cpu_cmpxchg_wide tests/cpu/cmpxchg_wide.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_cmpxchg_wide_lifted SHARED "${cmpxchg_wide_fixture}")
    add_test(NAME cpu_aot_cmpxchg_wide COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/cmpxchg_wide.py"
        check "$<TARGET_FILE:cpu_cmpxchg_wide>" "$<TARGET_FILE:cpu_cmpxchg_wide_lifted>")

    cpu_asm_fixture(cpu_cmov_setcc cmov_setcc)
    set(cmov_setcc_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_cmov_setcc_lifted.cpp")
    add_custom_command(OUTPUT "${cmov_setcc_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/cmov_setcc.py"
            emit "$<TARGET_FILE:cpu_cmov_setcc>" "${cmov_setcc_fixture}"
        DEPENDS cpu_cmov_setcc tests/cpu/cmov_setcc.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_cmov_setcc_lifted SHARED "${cmov_setcc_fixture}")
    add_test(NAME cpu_aot_cmov_setcc COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/cmov_setcc.py"
        check "$<TARGET_FILE:cpu_cmov_setcc>" "$<TARGET_FILE:cpu_cmov_setcc_lifted>")

    cpu_asm_fixture(cpu_signed_conds signed_conds)
    set(signed_conds_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_signed_conds_lifted.cpp")
    add_custom_command(OUTPUT "${signed_conds_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/signed_conds.py"
            emit "$<TARGET_FILE:cpu_signed_conds>" "${signed_conds_fixture}"
        DEPENDS cpu_signed_conds tests/cpu/signed_conds.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_signed_conds_lifted SHARED "${signed_conds_fixture}")
    add_test(NAME cpu_aot_signed_conds COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/signed_conds.py"
        check "$<TARGET_FILE:cpu_signed_conds>" "$<TARGET_FILE:cpu_signed_conds_lifted>")
    set_tests_properties(cpu_aot_signed_conds PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_adx adx)
    set(adx_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_adx_lifted.cpp")
    add_custom_command(OUTPUT "${adx_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/adx.py"
            emit "$<TARGET_FILE:cpu_adx>" "${adx_fixture}"
        DEPENDS cpu_adx tests/cpu/adx.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_adx_lifted SHARED "${adx_fixture}")
    add_test(NAME cpu_aot_adx COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/adx.py"
        check "$<TARGET_FILE:cpu_adx>" "$<TARGET_FILE:cpu_adx_lifted>")
    set_tests_properties(cpu_aot_adx PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx2_shifts avx2_shifts)
    set(avx2_shifts_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx2_shifts_lifted.cpp")
    add_custom_command(OUTPUT "${avx2_shifts_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx2_shifts.py"
            emit "$<TARGET_FILE:cpu_avx2_shifts>" "${avx2_shifts_fixture}"
        DEPENDS cpu_avx2_shifts tests/cpu/avx2_shifts.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx2_shifts_lifted SHARED "${avx2_shifts_fixture}")
    add_test(NAME cpu_aot_avx2_shifts COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx2_shifts.py"
        check "$<TARGET_FILE:cpu_avx2_shifts>" "$<TARGET_FILE:cpu_avx2_shifts_lifted>")
    set_tests_properties(cpu_aot_avx2_shifts PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx2_permutes avx2_permutes)
    set(avx2_permutes_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx2_permutes_lifted.cpp")
    add_custom_command(OUTPUT "${avx2_permutes_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx2_permutes.py"
            emit "$<TARGET_FILE:cpu_avx2_permutes>" "${avx2_permutes_fixture}"
        DEPENDS cpu_avx2_permutes tests/cpu/avx2_permutes.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx2_permutes_lifted SHARED "${avx2_permutes_fixture}")
    add_test(NAME cpu_aot_avx2_permutes COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx2_permutes.py"
        check "$<TARGET_FILE:cpu_avx2_permutes>" "$<TARGET_FILE:cpu_avx2_permutes_lifted>")
    set_tests_properties(cpu_aot_avx2_permutes PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_sse41_int sse41_int)
    set(sse41_int_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse41_int_lifted.cpp")
    add_custom_command(OUTPUT "${sse41_int_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse41_int.py"
            emit "$<TARGET_FILE:cpu_sse41_int>" "${sse41_int_fixture}"
        DEPENDS cpu_sse41_int tests/cpu/sse41_int.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse41_int_lifted SHARED "${sse41_int_fixture}")
    add_test(NAME cpu_aot_sse41_int COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse41_int.py"
        check "$<TARGET_FILE:cpu_sse41_int>" "$<TARGET_FILE:cpu_sse41_int_lifted>")
    set_tests_properties(cpu_aot_sse41_int PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_sse41_extend sse41_extend)
    set(sse41_extend_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse41_extend_lifted.cpp")
    add_custom_command(OUTPUT "${sse41_extend_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse41_extend.py"
            emit "$<TARGET_FILE:cpu_sse41_extend>" "${sse41_extend_fixture}"
        DEPENDS cpu_sse41_extend tests/cpu/sse41_extend.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse41_extend_lifted SHARED "${sse41_extend_fixture}")
    add_test(NAME cpu_aot_sse41_extend COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse41_extend.py"
        check "$<TARGET_FILE:cpu_sse41_extend>" "$<TARGET_FILE:cpu_sse41_extend_lifted>")
    set_tests_properties(cpu_aot_sse41_extend PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_sse2_sat_mul sse2_sat_mul)
    set(sse2_sat_mul_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse2_sat_mul_lifted.cpp")
    add_custom_command(OUTPUT "${sse2_sat_mul_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_sat_mul.py"
            emit "$<TARGET_FILE:cpu_sse2_sat_mul>" "${sse2_sat_mul_fixture}"
        DEPENDS cpu_sse2_sat_mul tests/cpu/sse2_sat_mul.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse2_sat_mul_lifted SHARED "${sse2_sat_mul_fixture}")
    add_test(NAME cpu_aot_sse2_sat_mul COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_sat_mul.py"
        check "$<TARGET_FILE:cpu_sse2_sat_mul>" "$<TARGET_FILE:cpu_sse2_sat_mul_lifted>")

    cpu_asm_fixture(cpu_crypto_aes_pclmul crypto_aes_pclmul)
    set(crypto_aes_pclmul_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_crypto_aes_pclmul_lifted.cpp")
    add_custom_command(OUTPUT "${crypto_aes_pclmul_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/crypto_aes_pclmul.py"
            emit "$<TARGET_FILE:cpu_crypto_aes_pclmul>" "${crypto_aes_pclmul_fixture}"
        DEPENDS cpu_crypto_aes_pclmul tests/cpu/crypto_aes_pclmul.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_crypto_aes_pclmul_lifted SHARED "${crypto_aes_pclmul_fixture}")
    add_test(NAME cpu_aot_crypto_aes_pclmul COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/crypto_aes_pclmul.py"
        check "$<TARGET_FILE:cpu_crypto_aes_pclmul>" "$<TARGET_FILE:cpu_crypto_aes_pclmul_lifted>")
    set_tests_properties(cpu_aot_crypto_aes_pclmul PROPERTIES SKIP_RETURN_CODE 77)

    # cpu_aot_aes_pclmul
    set(cpu_aes_pclmul_aot_exports
        "op_aesenc_reg,op_aesenclast_reg,op_aesdec_reg,op_aesdeclast_reg,"
        "op_aesimc_reg,op_aeskeygenassist_reg,"
        "op_pclmulqdq_00_reg,op_pclmulqdq_11_reg,op_pclmulqdq_ignore_bits_reg,"
        "op_aesenc_mem,op_aesenclast_mem,op_aesdec_mem,op_aesdeclast_mem,"
        "op_aesimc_mem,op_aeskeygenassist_mem,op_pclmulqdq_01_mem,"
        "op_vaesenc_reg,op_vaesenclast_reg,op_vaesdec_reg,op_vaesdeclast_reg,"
        "op_vaesimc_reg,op_vaeskeygenassist_reg,"
        "op_vpclmulqdq_10_reg,op_vpclmulqdq_ignore_bits_reg,"
        "op_vaesenc_mem,op_vaesenclast_mem,op_vaesdec_mem,op_vaesdeclast_mem,"
        "op_vaesimc_mem,op_vaeskeygenassist_mem,op_vpclmulqdq_11_mem,"
        "op_sse_preserves_ymm_hi,op_vex_zeroes_ymm_hi,op_vzeroupper_clears_ymm_hi,"
        "op_r8_source_then_store,op_dst_alias_src,op_aes_pclmul_discarded_read")
    string(CONCAT cpu_aes_pclmul_aot_exports ${cpu_aes_pclmul_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_aes_pclmul_aot_${variant} aes_pclmul_aot)
        cpu_translation(cpu_aes_pclmul_aot_${variant} cpu_aes_pclmul_aot "${cpu_aes_pclmul_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_aes_pclmul_aot_altered PRIVATE ALTER_AES_PCLMUL)
    add_test(NAME cpu_aot_aes_pclmul COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/aes_pclmul_aot_check.py"
        "$<TARGET_FILE:cpu_aes_pclmul_aot_original>"
        "$<TARGET_FILE:cpu_aes_pclmul_aot_original_lifted>"
        "$<TARGET_FILE:cpu_aes_pclmul_aot_altered>"
        "$<TARGET_FILE:cpu_aes_pclmul_aot_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_aes_pclmul PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_aes_pclmul.txt")

    # cpu_aot_sha256
    set(cpu_sha256_aot_exports
        "op_sha256rnds2_reg,op_sha256rnds2_mem,op_sha256rnds2_mem_r8,"
        "op_sha256rnds2_self_src,op_sha256rnds2_dst_xmm0,op_sha256rnds2_src_xmm0,op_sha256rnds2_all_xmm0,"
        "op_sha256msg1_reg,op_sha256msg1_mem,op_sha256msg1_self,"
        "op_sha256msg2_reg,op_sha256msg2_mem,op_sha256msg2_self,"
        "op_sha256_pipeline,op_sha256_discarded_read")
    string(CONCAT cpu_sha256_aot_exports ${cpu_sha256_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sha256_aot_${variant} sha256_aot)
        cpu_translation(cpu_sha256_aot_${variant} cpu_sha256_aot "${cpu_sha256_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_sha256_aot_altered PRIVATE ALTER_SHA256)
    add_test(NAME cpu_aot_sha256 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sha256_aot_check.py"
        "$<TARGET_FILE:cpu_sha256_aot_original>"
        "$<TARGET_FILE:cpu_sha256_aot_original_lifted>"
        "$<TARGET_FILE:cpu_sha256_aot_altered>"
        "$<TARGET_FILE:cpu_sha256_aot_altered_lifted>"
        "${CMAKE_CXX_COMPILER}")
    set_tests_properties(cpu_aot_sha256 PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_sha256.txt")

    cpu_asm_fixture(cpu_fma_scalar fma_scalar)
    set(fma_scalar_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_fma_scalar_lifted.cpp")
    add_custom_command(OUTPUT "${fma_scalar_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/fma_scalar.py"
            emit "$<TARGET_FILE:cpu_fma_scalar>" "${fma_scalar_fixture}"
        DEPENDS cpu_fma_scalar tests/cpu/fma_scalar.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_fma_scalar_lifted SHARED "${fma_scalar_fixture}")
    add_test(NAME cpu_aot_fma_scalar COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/fma_scalar.py"
        check "$<TARGET_FILE:cpu_fma_scalar>" "$<TARGET_FILE:cpu_fma_scalar_lifted>")
    set_tests_properties(cpu_aot_fma_scalar PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_sse2_int sse2_int)
    set(sse2_int_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse2_int_lifted.cpp")
    add_custom_command(OUTPUT "${sse2_int_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_int.py"
            emit "$<TARGET_FILE:cpu_sse2_int>" "${sse2_int_fixture}"
        DEPENDS cpu_sse2_int tests/cpu/sse2_int.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse2_int_lifted SHARED "${sse2_int_fixture}")
    add_test(NAME cpu_aot_sse2_int COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_int.py"
        check "$<TARGET_FILE:cpu_sse2_int>" "$<TARGET_FILE:cpu_sse2_int_lifted>")

    cpu_asm_fixture(cpu_sse41_42_misc sse41_42_misc)
    set(sse41_42_misc_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse41_42_misc_lifted.cpp")
    add_custom_command(OUTPUT "${sse41_42_misc_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse41_42_misc.py"
            emit "$<TARGET_FILE:cpu_sse41_42_misc>" "${sse41_42_misc_fixture}"
        DEPENDS cpu_sse41_42_misc tests/cpu/sse41_42_misc.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse41_42_misc_lifted SHARED "${sse41_42_misc_fixture}")
    add_test(NAME cpu_aot_sse41_42_misc COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse41_42_misc.py"
        check "$<TARGET_FILE:cpu_sse41_42_misc>" "$<TARGET_FILE:cpu_sse41_42_misc_lifted>")
    set_tests_properties(cpu_aot_sse41_42_misc PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_ssse3_int ssse3_int)
    set(ssse3_int_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_ssse3_int_lifted.cpp")
    add_custom_command(OUTPUT "${ssse3_int_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/ssse3_int.py"
            emit "$<TARGET_FILE:cpu_ssse3_int>" "${ssse3_int_fixture}"
        DEPENDS cpu_ssse3_int tests/cpu/ssse3_int.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_ssse3_int_lifted SHARED "${ssse3_int_fixture}")
    add_test(NAME cpu_aot_ssse3_int COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/ssse3_int.py"
        check "$<TARGET_FILE:cpu_ssse3_int>" "$<TARGET_FILE:cpu_ssse3_int_lifted>")
    set_tests_properties(cpu_aot_ssse3_int PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_sse2_shifts_pack sse2_shifts_pack)
    set(sse2_shifts_pack_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse2_shifts_pack_lifted.cpp")
    add_custom_command(OUTPUT "${sse2_shifts_pack_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_shifts_pack.py"
            emit "$<TARGET_FILE:cpu_sse2_shifts_pack>" "${sse2_shifts_pack_fixture}"
        DEPENDS cpu_sse2_shifts_pack tests/cpu/sse2_shifts_pack.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse2_shifts_pack_lifted SHARED "${sse2_shifts_pack_fixture}")
    add_test(NAME cpu_aot_sse2_shifts_pack COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse2_shifts_pack.py"
        check "$<TARGET_FILE:cpu_sse2_shifts_pack>" "$<TARGET_FILE:cpu_sse2_shifts_pack_lifted>")

    cpu_asm_fixture(cpu_float_shuffles float_shuffles)
    set(float_shuffles_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_float_shuffles_lifted.cpp")
    add_custom_command(OUTPUT "${float_shuffles_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/float_shuffles.py"
            emit "$<TARGET_FILE:cpu_float_shuffles>" "${float_shuffles_fixture}"
        DEPENDS cpu_float_shuffles tests/cpu/float_shuffles.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_float_shuffles_lifted SHARED "${float_shuffles_fixture}")
    add_test(NAME cpu_aot_float_shuffles COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/float_shuffles.py"
        check "$<TARGET_FILE:cpu_float_shuffles>" "$<TARGET_FILE:cpu_float_shuffles_lifted>")
    set_tests_properties(cpu_aot_float_shuffles PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_float_packed float_packed)
    set(float_packed_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_float_packed_lifted.cpp")
    add_custom_command(OUTPUT "${float_packed_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/float_packed.py"
            emit "$<TARGET_FILE:cpu_float_packed>" "${float_packed_fixture}"
        DEPENDS cpu_float_packed tests/cpu/float_packed.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_float_packed_lifted SHARED "${float_packed_fixture}")
    add_test(NAME cpu_aot_float_packed COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/float_packed.py"
        check "$<TARGET_FILE:cpu_float_packed>" "$<TARGET_FILE:cpu_float_packed_lifted>")
    set_tests_properties(cpu_aot_float_packed PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_float_conversions float_conversions)
    set(float_conversions_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_float_conversions_lifted.cpp")
    add_custom_command(OUTPUT "${float_conversions_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/float_conversions.py"
            emit "$<TARGET_FILE:cpu_float_conversions>" "${float_conversions_fixture}"
        DEPENDS cpu_float_conversions tests/cpu/float_conversions.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_float_conversions_lifted SHARED "${float_conversions_fixture}")
    add_test(NAME cpu_aot_float_conversions COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/float_conversions.py"
        check "$<TARGET_FILE:cpu_float_conversions>" "$<TARGET_FILE:cpu_float_conversions_lifted>")
    set_tests_properties(cpu_aot_float_conversions PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_fma_packed fma_packed)
    set(fma_packed_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_fma_packed_lifted.cpp")
    add_custom_command(OUTPUT "${fma_packed_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/fma_packed.py"
            emit "$<TARGET_FILE:cpu_fma_packed>" "${fma_packed_fixture}"
        DEPENDS cpu_fma_packed tests/cpu/fma_packed.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_fma_packed_lifted SHARED "${fma_packed_fixture}")
    add_test(NAME cpu_aot_fma_packed COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/fma_packed.py"
        check "$<TARGET_FILE:cpu_fma_packed>" "$<TARGET_FILE:cpu_fma_packed_lifted>")
    set_tests_properties(cpu_aot_fma_packed PROPERTIES SKIP_RETURN_CODE 77)
    add_dependencies(cpu_fma3_leaf_original cpu_fma_packed_lifted)

    cpu_asm_fixture(cpu_sse34_fp sse34_fp)
    set(sse34_fp_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_sse34_fp_lifted.cpp")
    add_custom_command(OUTPUT "${sse34_fp_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse34_fp.py"
            emit "$<TARGET_FILE:cpu_sse34_fp>" "${sse34_fp_fixture}"
        DEPENDS cpu_sse34_fp tests/cpu/sse34_fp.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_sse34_fp_lifted SHARED "${sse34_fp_fixture}")
    add_test(NAME cpu_aot_sse34_fp COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/sse34_fp.py"
        check "$<TARGET_FILE:cpu_sse34_fp>" "$<TARGET_FILE:cpu_sse34_fp_lifted>")
    set_tests_properties(cpu_aot_sse34_fp PROPERTIES SKIP_RETURN_CODE 77)

    # cpu_aot_sse41_fp
    set(cpu_sse41_fp_aot_exports
        "op_roundps_reg_0,op_roundps_reg_1,op_roundps_reg_2,op_roundps_reg_3,op_roundps_reg_4,op_roundps_reg_8,"
        "op_roundps_mem_rcx,op_roundps_mem_rdx,op_roundps_mem_r8,"
        "op_roundpd_reg_0,op_roundpd_reg_1,op_roundpd_reg_2,op_roundpd_reg_3,op_roundpd_reg_4,"
        "op_roundpd_mem_rcx,op_roundpd_mem_rdx,op_roundpd_mem_r8,"
        "op_roundss_reg_0,op_roundss_reg_1,op_roundss_reg_2,op_roundss_reg_3,op_roundss_reg_4,"
        "op_roundss_mem_rcx,op_roundss_mem_rdx,op_roundss_mem_r8,"
        "op_roundsd_reg_0,op_roundsd_reg_1,op_roundsd_reg_2,op_roundsd_reg_3,op_roundsd_reg_4,"
        "op_roundsd_mem_rcx,op_roundsd_mem_rdx,op_roundsd_mem_r8,"
        "op_dpps_reg_f1,op_dpps_reg_ff,op_dpps_reg_5a,op_dpps_reg_0f,"
        "op_dpps_mem_rcx,op_dpps_mem_rdx,op_dpps_mem_r8,"
        "op_dppd_reg_33,op_dppd_reg_11,op_dppd_reg_22,op_dppd_reg_03,"
        "op_dppd_mem_rcx,op_dppd_mem_rdx,op_dppd_mem_r8,"
        "op_insertps_reg_s1_d2_z5,op_insertps_reg_s3_d0_z0,op_insertps_reg_s0_d3_z8,"
        "op_insertps_mem_rcx,op_insertps_mem_rdx,op_insertps_mem_r8,"
        "op_extractps_r32_lane2,op_extractps_r64_lane3,op_extractps_mem_lane1,"
        "op_sse41_glue_pipeline")
    string(CONCAT cpu_sse41_fp_aot_exports ${cpu_sse41_fp_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_sse41_fp_aot_${variant} sse41_fp_aot)
        cpu_translation(cpu_sse41_fp_aot_${variant} cpu_sse41_fp_aot "${cpu_sse41_fp_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_sse41_fp_aot_altered PRIVATE ALTER_SSE41_FP)
    add_test(NAME cpu_aot_sse41_fp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/sse41_fp_aot_check.py"
        "$<TARGET_FILE:cpu_sse41_fp_aot_original>"
        "$<TARGET_FILE:cpu_sse41_fp_aot_original_lifted>"
        "$<TARGET_FILE:cpu_sse41_fp_aot_altered>"
        "$<TARGET_FILE:cpu_sse41_fp_aot_altered_lifted>")
    set_tests_properties(cpu_aot_sse41_fp PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_sse41_fp.txt")

    cpu_asm_fixture(cpu_avx_packed_int avx_packed_int)
    set(avx_packed_int_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_packed_int_lifted.cpp")
    add_custom_command(OUTPUT "${avx_packed_int_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_packed_int.py"
            emit "$<TARGET_FILE:cpu_avx_packed_int>" "${avx_packed_int_fixture}"
        DEPENDS cpu_avx_packed_int tests/cpu/avx_packed_int.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_packed_int_lifted SHARED "${avx_packed_int_fixture}")
    add_test(NAME cpu_aot_avx_packed_int COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_packed_int.py"
        check "$<TARGET_FILE:cpu_avx_packed_int>" "$<TARGET_FILE:cpu_avx_packed_int_lifted>")
    set_tests_properties(cpu_aot_avx_packed_int PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx_packed_fp avx_packed_fp)
    set(avx_packed_fp_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_packed_fp_lifted.cpp")
    add_custom_command(OUTPUT "${avx_packed_fp_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_packed_fp.py"
            emit "$<TARGET_FILE:cpu_avx_packed_fp>" "${avx_packed_fp_fixture}"
        DEPENDS cpu_avx_packed_fp tests/cpu/avx_packed_fp.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_packed_fp_lifted SHARED "${avx_packed_fp_fixture}")
    add_test(NAME cpu_aot_avx_packed_fp COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_packed_fp.py"
        check "$<TARGET_FILE:cpu_avx_packed_fp>" "$<TARGET_FILE:cpu_avx_packed_fp_lifted>")
    set_tests_properties(cpu_aot_avx_packed_fp PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx_int_minmax_mul avx_int_minmax_mul)
    set(avx_int_minmax_mul_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_int_minmax_mul_lifted.cpp")
    add_custom_command(OUTPUT "${avx_int_minmax_mul_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_minmax_mul.py"
            emit "$<TARGET_FILE:cpu_avx_int_minmax_mul>" "${avx_int_minmax_mul_fixture}"
        DEPENDS cpu_avx_int_minmax_mul tests/cpu/avx_int_minmax_mul.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_int_minmax_mul_lifted SHARED "${avx_int_minmax_mul_fixture}")
    add_test(NAME cpu_aot_avx_int_minmax_mul COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_minmax_mul.py"
        check "$<TARGET_FILE:cpu_avx_int_minmax_mul>" "$<TARGET_FILE:cpu_avx_int_minmax_mul_lifted>")
    set_tests_properties(cpu_aot_avx_int_minmax_mul PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx_int_extend_hadd avx_int_extend_hadd)
    set(avx_int_extend_hadd_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_int_extend_hadd_lifted.cpp")
    add_custom_command(OUTPUT "${avx_int_extend_hadd_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_extend_hadd.py"
            emit "$<TARGET_FILE:cpu_avx_int_extend_hadd>" "${avx_int_extend_hadd_fixture}"
        DEPENDS cpu_avx_int_extend_hadd tests/cpu/avx_int_extend_hadd.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_int_extend_hadd_lifted SHARED "${avx_int_extend_hadd_fixture}")
    add_test(NAME cpu_aot_avx_int_extend_hadd COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_extend_hadd.py"
        check "$<TARGET_FILE:cpu_avx_int_extend_hadd>" "$<TARGET_FILE:cpu_avx_int_extend_hadd_lifted>")
    set_tests_properties(cpu_aot_avx_int_extend_hadd PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx_horiz_fp avx_horiz_fp)
    set(avx_horiz_fp_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_horiz_fp_lifted.cpp")
    add_custom_command(OUTPUT "${avx_horiz_fp_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_horiz_fp.py"
            emit "$<TARGET_FILE:cpu_avx_horiz_fp>" "${avx_horiz_fp_fixture}"
        DEPENDS cpu_avx_horiz_fp tests/cpu/avx_horiz_fp.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_horiz_fp_lifted SHARED "${avx_horiz_fp_fixture}")
    add_test(NAME cpu_aot_avx_horiz_fp COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_horiz_fp.py"
        check "$<TARGET_FILE:cpu_avx_horiz_fp>" "$<TARGET_FILE:cpu_avx_horiz_fp_lifted>")
    set_tests_properties(cpu_aot_avx_horiz_fp PROPERTIES SKIP_RETURN_CODE 77)

    # cpu_aot_avx_horiz_fp_dedicated
    set(cpu_avx_horiz_fp_aot_exports
        "op_vhaddps_xmm_reg,op_vhaddpd_xmm_reg,op_vhsubps_xmm_reg,op_vhsubpd_xmm_reg,"
        "op_vaddsubps_xmm_reg,op_vaddsubpd_xmm_reg,"
        "op_vhaddps_xmm_mem,op_vhaddpd_xmm_mem,op_vhsubps_xmm_mem,op_vhsubpd_xmm_mem,"
        "op_vaddsubps_xmm_mem,op_vaddsubpd_xmm_mem,"
        "op_vhaddps_ymm_reg,op_vhaddpd_ymm_reg,op_vhsubps_ymm_reg,op_vhsubpd_ymm_reg,"
        "op_vaddsubps_ymm_reg,op_vaddsubpd_ymm_reg,"
        "op_vhaddps_ymm_mem,op_vhaddpd_ymm_mem,op_vhsubps_ymm_mem,op_vhsubpd_ymm_mem,"
        "op_vaddsubps_ymm_mem,op_vaddsubpd_ymm_mem,"
        "op_vhaddps_ymm_mem_rcx,op_vaddsubpd_ymm_mem_r8,"
        "op_vhaddps_ymm_alias_dst_src1,op_vhaddpd_ymm_alias_dst_src2,"
        "op_vhsubps_ymm_alias_src1_src2,op_vaddsubps_ymm_alias_all,op_vaddsubpd_xmm_alias_dst_src2")
    string(CONCAT cpu_avx_horiz_fp_aot_exports ${cpu_avx_horiz_fp_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_horiz_fp_aot_${variant} avx_horiz_fp_aot)
        cpu_translation(cpu_avx_horiz_fp_aot_${variant} cpu_avx_horiz_fp_aot "${cpu_avx_horiz_fp_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_avx_horiz_fp_aot_altered PRIVATE ALTER_AVX_HORIZ_FP)
    add_test(NAME cpu_aot_avx_horiz_fp_dedicated COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_horiz_fp_aot_check.py"
        "$<TARGET_FILE:cpu_avx_horiz_fp_aot_original>"
        "$<TARGET_FILE:cpu_avx_horiz_fp_aot_original_lifted>"
        "$<TARGET_FILE:cpu_avx_horiz_fp_aot_altered>"
        "$<TARGET_FILE:cpu_avx_horiz_fp_aot_altered_lifted>")
    set_tests_properties(cpu_aot_avx_horiz_fp_dedicated PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_horiz_fp_dedicated.txt")

    cpu_asm_fixture(cpu_avx_addsub_fp avx_addsub_fp)
    set(avx_addsub_fp_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_addsub_fp_lifted.cpp")
    add_custom_command(OUTPUT "${avx_addsub_fp_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_addsub_fp.py"
            emit "$<TARGET_FILE:cpu_avx_addsub_fp>" "${avx_addsub_fp_fixture}"
        DEPENDS cpu_avx_addsub_fp tests/cpu/avx_addsub_fp.py tests/cpu/avx_horiz_fp.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_addsub_fp_lifted SHARED "${avx_addsub_fp_fixture}")
    add_test(NAME cpu_aot_avx_addsub_fp COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_addsub_fp.py"
        check "$<TARGET_FILE:cpu_avx_addsub_fp>" "$<TARGET_FILE:cpu_avx_addsub_fp_lifted>")
    set_tests_properties(cpu_aot_avx_addsub_fp PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx_int_shifts_pack avx_int_shifts_pack)
    set(avx_int_shifts_pack_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_int_shifts_pack_lifted.cpp")
    add_custom_command(OUTPUT "${avx_int_shifts_pack_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_shifts_pack.py"
            emit "$<TARGET_FILE:cpu_avx_int_shifts_pack>" "${avx_int_shifts_pack_fixture}"
        DEPENDS cpu_avx_int_shifts_pack tests/cpu/avx_int_shifts_pack.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_int_shifts_pack_lifted SHARED "${avx_int_shifts_pack_fixture}")
    add_test(NAME cpu_aot_avx_int_shifts_pack COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_int_shifts_pack.py"
        check "$<TARGET_FILE:cpu_avx_int_shifts_pack>" "$<TARGET_FILE:cpu_avx_int_shifts_pack_lifted>")
    set_tests_properties(cpu_aot_avx_int_shifts_pack PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx_shuffle_blend avx_shuffle_blend)
    set(avx_shuffle_blend_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_shuffle_blend_lifted.cpp")
    add_custom_command(OUTPUT "${avx_shuffle_blend_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_shuffle_blend.py"
            emit "$<TARGET_FILE:cpu_avx_shuffle_blend>" "${avx_shuffle_blend_fixture}"
        DEPENDS cpu_avx_shuffle_blend tests/cpu/avx_shuffle_blend.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_shuffle_blend_lifted SHARED "${avx_shuffle_blend_fixture}")
    add_test(NAME cpu_aot_avx_shuffle_blend COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_shuffle_blend.py"
        check "$<TARGET_FILE:cpu_avx_shuffle_blend>" "$<TARGET_FILE:cpu_avx_shuffle_blend_lifted>")
    set_tests_properties(cpu_aot_avx_shuffle_blend PROPERTIES SKIP_RETURN_CODE 77)

    cpu_asm_fixture(cpu_avx_cvt_cmp_test avx_cvt_cmp_test)
    set(avx_cvt_cmp_test_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_cvt_cmp_test_lifted.cpp")
    add_custom_command(OUTPUT "${avx_cvt_cmp_test_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_cvt_cmp_test.py"
            emit "$<TARGET_FILE:cpu_avx_cvt_cmp_test>" "${avx_cvt_cmp_test_fixture}"
        DEPENDS cpu_avx_cvt_cmp_test tests/cpu/avx_cvt_cmp_test.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_cvt_cmp_test_lifted SHARED "${avx_cvt_cmp_test_fixture}")
    add_test(NAME cpu_aot_avx_cvt_cmp_test COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_cvt_cmp_test.py"
        check "$<TARGET_FILE:cpu_avx_cvt_cmp_test>" "$<TARGET_FILE:cpu_avx_cvt_cmp_test_lifted>")
    set_tests_properties(cpu_aot_avx_cvt_cmp_test PROPERTIES SKIP_RETURN_CODE 77)

    # cpu_aot_avx_cmp
    set(cpu_avx_cmp_aot_exports)
    foreach(mnem IN ITEMS vcmpps_ymm vcmppd_ymm vcmpss vcmpsd)
        foreach(hi IN ITEMS 0 1)
            foreach(lo IN ITEMS 0 1 2 3 4 5 6 7 8 9 a b c d e f)
                list(APPEND cpu_avx_cmp_aot_exports "op_${mnem}_p${hi}${lo}")
            endforeach()
        endforeach()
    endforeach()
    list(APPEND cpu_avx_cmp_aot_exports
        op_vcmpps_xmm_reg op_vcmppd_xmm_reg op_vcmpps_xmm_mem op_vcmppd_xmm_mem
        op_vcmpps_ymm_mem_rcx op_vcmpps_ymm_mem_rdx op_vcmpps_ymm_mem_r8
        op_vcmppd_ymm_mem_rcx op_vcmppd_ymm_mem_rdx op_vcmppd_ymm_mem_r8
        op_vcmpss_mem_rcx op_vcmpss_mem_rdx op_vcmpss_mem_r8
        op_vcmpsd_mem_rcx op_vcmpsd_mem_rdx op_vcmpsd_mem_r8
        op_vcmpps_imm_highbits
        op_vcmpps_alias_dst_src1 op_vcmppd_alias_dst_src2 op_vcmpps_alias_src1_src2 op_vcmpsd_alias_all
        op_vmovss_mem_glue op_vmovsd_mem_glue op_vmovss_reg_merge_glue op_vmovsd_reg_merge_glue
        op_vmov_aligned_glue)
    string(JOIN "," cpu_avx_cmp_aot_exports_csv ${cpu_avx_cmp_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_avx_cmp_aot_${variant} avx_cmp_aot)
        cpu_translation(cpu_avx_cmp_aot_${variant} cpu_avx_cmp_aot "${cpu_avx_cmp_aot_exports_csv}")
    endforeach()
    target_compile_definitions(cpu_avx_cmp_aot_altered PRIVATE ALTER_AVX_CMP)
    add_test(NAME cpu_aot_avx_cmp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/avx_cmp_aot_check.py"
        "$<TARGET_FILE:cpu_avx_cmp_aot_original>"
        "$<TARGET_FILE:cpu_avx_cmp_aot_original_lifted>"
        "$<TARGET_FILE:cpu_avx_cmp_aot_altered>"
        "$<TARGET_FILE:cpu_avx_cmp_aot_altered_lifted>")
    set_tests_properties(cpu_aot_avx_cmp PROPERTIES
        SKIP_RETURN_CODE 77
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_avx_cmp.txt")

    cpu_asm_fixture(cpu_avx_scalar_fp avx_scalar_fp)
    set(avx_scalar_fp_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_avx_scalar_fp_lifted.cpp")
    add_custom_command(OUTPUT "${avx_scalar_fp_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_scalar_fp.py"
            emit "$<TARGET_FILE:cpu_avx_scalar_fp>" "${avx_scalar_fp_fixture}"
        DEPENDS cpu_avx_scalar_fp tests/cpu/avx_scalar_fp.py tools/ffx_version_query.py
            tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(cpu_avx_scalar_fp_lifted SHARED "${avx_scalar_fp_fixture}")
    add_test(NAME cpu_aot_avx_scalar_fp COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/avx_scalar_fp.py"
        check "$<TARGET_FILE:cpu_avx_scalar_fp>" "$<TARGET_FILE:cpu_avx_scalar_fp_lifted>")
    set_tests_properties(cpu_aot_avx_scalar_fp PROPERTIES SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_vex_parity vex_parity)
    # The lifted DLL, an explicit /O2 build, and two mutated controls (stalepf, swap) that must mismatch.
    set(vex_parity_control_files "")
    foreach(variant IN ITEMS lifted stalepf swap)
        set(vex_parity_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_parity_${variant}.cpp")
        add_custom_command(OUTPUT "${vex_parity_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/vex_parity.py"
                emit "$<TARGET_FILE:cpu_vex_parity>" "${vex_parity_fixture}" ${variant}
            DEPENDS cpu_vex_parity tests/cpu/vex_parity.py tools/ffx_version_query.py tools/x87_lower.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_vex_parity_${variant} SHARED "${vex_parity_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND vex_parity_control_files "$<TARGET_FILE:cpu_vex_parity_${variant}>")
        endif()
    endforeach()
    set(vex_parity_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_parity_lifted_o2.dll")
    add_custom_command(OUTPUT "${vex_parity_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /EHsc /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_parity_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_parity_lifted_o2.obj" "/Fe${vex_parity_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_vex_parity_lifted.cpp" VERBATIM)
    add_custom_target(cpu_vex_parity_lifted_o2 ALL DEPENDS "${vex_parity_o2}")
    add_test(NAME cpu_aot_vex_parity COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/vex_parity.py"
        check "$<TARGET_FILE:cpu_guarded_call>" "$<TARGET_FILE:cpu_vex_parity>"
        "$<TARGET_FILE:cpu_vex_parity_lifted>" "${vex_parity_o2}" ${vex_parity_control_files})
    set_tests_properties(cpu_aot_vex_parity PROPERTIES SKIP_RETURN_CODE 77)
    cpu_translation(cpu_callback cpu_chained_aot call_context CALLBACK_OFFSET 8)
    cpu_asm_fixture(cpu_xlatb xlatb)
    # The lifted DLL and three mutated controls that the check requires to mismatch.
    foreach(variant IN ITEMS lifted signed noaddr32 clear)
        set(xlatb_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_xlatb_${variant}.cpp")
        add_custom_command(OUTPUT "${xlatb_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/xlatb.py"
                emit "$<TARGET_FILE:cpu_xlatb>" "${xlatb_fixture}" ${variant}
            DEPENDS cpu_xlatb tests/cpu/xlatb.py tools/ffx_version_query.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_xlatb_${variant} SHARED "${xlatb_fixture}")
    endforeach()
    add_test(NAME cpu_aot_xlatb COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/xlatb.py"
        check "$<TARGET_FILE:cpu_xlatb>" "$<TARGET_FILE:cpu_xlatb_lifted>"
        "$<TARGET_FILE:cpu_xlatb_signed>" "$<TARGET_FILE:cpu_xlatb_noaddr32>" "$<TARGET_FILE:cpu_xlatb_clear>")
    cpu_asm_fixture(cpu_rdtsc_harness rdtsc_harness)
    # RDTSC runs on every host. RDTSCP has its own fixture and test, which exits 77 on a host without it. Each
    # part has a lifted DLL, mutated controls that its check requires to break a property, and /O2 builds;
    # plain removes volatile and is built only at /O2.
    foreach(part IN ITEMS rdtsc rdtscp)
        cpu_asm_fixture(cpu_${part} ${part})
        if(part STREQUAL "rdtsc")
            set(tsc_variants lifted constant swap noext stale flags plain)
            set(tsc_o2_variants lifted plain)
        else()
            set(tsc_variants lifted swap noext noaux pflags)
            set(tsc_o2_variants lifted)
        endif()
        set(tsc_controls)
        foreach(variant IN LISTS tsc_variants)
            set(tsc_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp")
            add_custom_command(OUTPUT "${tsc_fixture}"
                COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rdtsc.py"
                    emit ${part} "$<TARGET_FILE:cpu_${part}>" "${tsc_fixture}" ${variant}
                DEPENDS cpu_${part} tests/cpu/rdtsc.py tools/ffx_version_query.py tools/x87_lower.py
                    tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
            if(NOT variant STREQUAL "plain")
                add_library(cpu_${part}_${variant} SHARED "${tsc_fixture}")
                if(NOT variant STREQUAL "lifted")
                    list(APPEND tsc_controls "$<TARGET_FILE:cpu_${part}_${variant}>")
                endif()
            endif()
        endforeach()
        foreach(variant IN LISTS tsc_o2_variants)
            set(tsc_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}_o2.dll")
            add_custom_command(OUTPUT "${tsc_o2}"
                COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp"
                    "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}_o2.obj" "/Fe${tsc_o2}"
                DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp" VERBATIM)
            add_custom_target(cpu_${part}_${variant}_o2 ALL DEPENDS "${tsc_o2}")
            list(APPEND tsc_controls "${tsc_o2}")
        endforeach()
        add_test(NAME cpu_aot_${part} COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rdtsc.py"
            check ${part} "$<TARGET_FILE:cpu_rdtsc_harness>" "$<TARGET_FILE:cpu_${part}>"
            "$<TARGET_FILE:cpu_${part}_lifted>" ${tsc_controls})
    endforeach()
    set_tests_properties(cpu_aot_rdtscp PROPERTIES SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_rdrand_harness rdrand_harness)
    # The opt-in host-entropy profile. RDRAND and RDSEED have their own fixtures and tests, each exiting 77 when
    # the host lacks the instruction. Each part has the lifted DLL, deterministic succeed and fail variants that
    # must pass, mutated controls that must break a rule, and /O2 builds; plain removes volatile and is built
    # only at /O2.
    foreach(part IN ITEMS rdrand rdseed)
        cpu_asm_fixture(cpu_${part} ${part})
        set(entropy_extras)
        foreach(variant IN ITEMS lifted succeed fail constant nocarry noext wide16 flags nozero plain)
            set(entropy_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp")
            add_custom_command(OUTPUT "${entropy_fixture}"
                COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rdrand.py"
                    emit ${part} "$<TARGET_FILE:cpu_${part}>" "${entropy_fixture}" ${variant}
                DEPENDS cpu_${part} tests/cpu/rdrand.py tools/ffx_version_query.py tools/x87_lower.py
                    tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
            if(NOT variant STREQUAL "plain")
                add_library(cpu_${part}_${variant} SHARED "${entropy_fixture}")
                if(NOT variant STREQUAL "lifted")
                    list(APPEND entropy_extras "$<TARGET_FILE:cpu_${part}_${variant}>")
                endif()
            endif()
        endforeach()
        foreach(variant IN ITEMS lifted plain)
            set(entropy_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}_o2.dll")
            add_custom_command(OUTPUT "${entropy_o2}"
                COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp"
                    "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}_o2.obj" "/Fe${entropy_o2}"
                DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp" VERBATIM)
            add_custom_target(cpu_${part}_${variant}_o2 ALL DEPENDS "${entropy_o2}")
            list(APPEND entropy_extras "${entropy_o2}")
        endforeach()
        add_test(NAME cpu_aot_${part} COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/rdrand.py"
            check ${part} "$<TARGET_FILE:cpu_rdrand_harness>" "$<TARGET_FILE:cpu_${part}>"
            "$<TARGET_FILE:cpu_${part}_lifted>" ${entropy_extras})
        set_tests_properties(cpu_aot_${part} PROPERTIES SKIP_RETURN_CODE 77)
    endforeach()
    cpu_asm_fixture(cpu_cpuid_harness cpuid_harness)
    # The opt-in host-CPU profile. CPUID and XGETBV have their own fixtures and tests; cpu_aot_xgetbv exits 77
    # without OSXSAVE, and cpu_aot_cpuid when no covered leaf depends on the subleaf. Each part has the lifted
    # DLL, mutated controls that must break a property, and /O2 builds; XGETBV's plain removes volatile and is
    # built only at /O2.
    foreach(part IN ITEMS cpuid xgetbv)
        cpu_asm_fixture(cpu_${part} ${part})
        if(part STREQUAL "cpuid")
            set(host_cpu_variants lifted noext swap nosubleaf constant flags)
            set(host_cpu_o2_variants lifted)
        else()
            set(host_cpu_variants lifted noext swap constant flags plain)
            set(host_cpu_o2_variants lifted plain)
        endif()
        set(host_cpu_extras)
        foreach(variant IN LISTS host_cpu_variants)
            set(host_cpu_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp")
            add_custom_command(OUTPUT "${host_cpu_fixture}"
                COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/cpuid.py"
                    emit ${part} "$<TARGET_FILE:cpu_${part}>" "${host_cpu_fixture}" ${variant}
                DEPENDS cpu_${part} tests/cpu/cpuid.py tools/ffx_version_query.py tools/x87_lower.py
                    tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
            if(NOT variant STREQUAL "plain")
                add_library(cpu_${part}_${variant} SHARED "${host_cpu_fixture}")
                if(NOT variant STREQUAL "lifted")
                    list(APPEND host_cpu_extras "$<TARGET_FILE:cpu_${part}_${variant}>")
                endif()
            endif()
        endforeach()
        foreach(variant IN LISTS host_cpu_o2_variants)
            set(host_cpu_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}_o2.dll")
            add_custom_command(OUTPUT "${host_cpu_o2}"
                COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp"
                    "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}_o2.obj" "/Fe${host_cpu_o2}"
                DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_${part}_${variant}.cpp" VERBATIM)
            add_custom_target(cpu_${part}_${variant}_o2 ALL DEPENDS "${host_cpu_o2}")
            list(APPEND host_cpu_extras "${host_cpu_o2}")
        endforeach()
        add_test(NAME cpu_aot_${part} COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/cpuid.py"
            check ${part} "$<TARGET_FILE:cpu_cpuid_harness>" "$<TARGET_FILE:cpu_${part}>"
            "$<TARGET_FILE:cpu_${part}_lifted>" ${host_cpu_extras})
        set_tests_properties(cpu_aot_${part} PROPERTIES SKIP_RETURN_CODE 77)
    endforeach()
    # INT3, UD2 and UD1: the lifted DLL, the drop, swap, nostore, udonedrop and udoneload controls that must break
    # a rule, an /O2 build,
    # and the native SEH boundary that the check's child processes call through.
    cpu_asm_fixture(cpu_trap trap)
    add_library(cpu_trap_harness SHARED tests/cpu/trap_harness.cpp)
    set(trap_controls)
    foreach(variant IN ITEMS lifted drop swap nostore udonedrop udoneload)
        set(trap_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_trap_${variant}.cpp")
        add_custom_command(OUTPUT "${trap_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/trap.py"
                emit "$<TARGET_FILE:cpu_trap>" "${trap_fixture}" ${variant}
            DEPENDS cpu_trap tests/cpu/trap.py tools/ffx_version_query.py tools/x87_lower.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_trap_${variant} SHARED "${trap_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND trap_controls "$<TARGET_FILE:cpu_trap_${variant}>")
        endif()
    endforeach()
    set(trap_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_trap_lifted_o2.dll")
    add_custom_command(OUTPUT "${trap_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /EHsc /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_trap_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_trap_lifted_o2.obj" "/Fe${trap_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_trap_lifted.cpp" VERBATIM)
    add_custom_target(cpu_trap_lifted_o2 ALL DEPENDS "${trap_o2}")
    add_test(NAME cpu_aot_trap COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/trap.py"
        check "$<TARGET_FILE:cpu_trap_harness>" "$<TARGET_FILE:cpu_trap>" "$<TARGET_FILE:cpu_trap_lifted>"
        ${trap_controls} "${trap_o2}")
    # UD1 is written as bytes, so the check records the decoded forms for tools/form_coverage.py.
    set_tests_properties(cpu_aot_trap PROPERTIES
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_trap.txt")
    # The opt-in host-MXCSR profile: the lifted DLL, the noload and fixed controls that must break a rule, and
    # an /O2 build of the translation.
    cpu_asm_fixture(cpu_mxcsr_harness mxcsr_harness)
    # The scalar float check loads the harness, and $<TARGET_FILE:> adds no build dependency, so the
    # two translations the documented build names must build it too.
    add_dependencies(cpu_float_original_lifted cpu_mxcsr_harness)
    add_dependencies(cpu_float_swapped_lifted cpu_mxcsr_harness)
    cpu_asm_fixture(cpu_mxcsr mxcsr)
    set(mxcsr_controls)
    foreach(variant IN ITEMS lifted noload fixed)
        set(mxcsr_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_${variant}.cpp")
        add_custom_command(OUTPUT "${mxcsr_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/mxcsr.py"
                emit "$<TARGET_FILE:cpu_mxcsr>" "${mxcsr_fixture}" ${variant}
            DEPENDS cpu_mxcsr tests/cpu/mxcsr.py tools/ffx_version_query.py tools/x87_lower.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_mxcsr_${variant} SHARED "${mxcsr_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND mxcsr_controls "$<TARGET_FILE:cpu_mxcsr_${variant}>")
        endif()
    endforeach()
    set(mxcsr_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_lifted_o2.dll")
    add_custom_command(OUTPUT "${mxcsr_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /EHsc /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_lifted_o2.obj" "/Fe${mxcsr_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_lifted.cpp" VERBATIM)
    add_custom_target(cpu_mxcsr_lifted_o2 ALL DEPENDS "${mxcsr_o2}")
    add_test(NAME cpu_aot_mxcsr COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/mxcsr.py"
        check "$<TARGET_FILE:cpu_mxcsr_harness>" "$<TARGET_FILE:cpu_mxcsr>" "$<TARGET_FILE:cpu_mxcsr_lifted>"
        ${mxcsr_controls} "${mxcsr_o2}")
    # VLDMXCSR and VSTMXCSR: the translated part runs without AVX and never skips; the native comparison is its
    # own test and exits 77 on a host that cannot execute VEX instructions.
    cpu_asm_fixture(cpu_vmxcsr vmxcsr)
    set(vmxcsr_controls)
    foreach(variant IN ITEMS lifted noload fixed unmasked mixldload mixvstread mixvldload mixstread)
        set(vmxcsr_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_vmxcsr_${variant}.cpp")
        add_custom_command(OUTPUT "${vmxcsr_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/vmxcsr.py"
                emit "$<TARGET_FILE:cpu_vmxcsr>" "${vmxcsr_fixture}" ${variant}
            DEPENDS cpu_vmxcsr tests/cpu/vmxcsr.py tests/cpu/mxcsr.py tools/ffx_version_query.py tools/x87_lower.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_vmxcsr_${variant} SHARED "${vmxcsr_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND vmxcsr_controls "$<TARGET_FILE:cpu_vmxcsr_${variant}>")
        endif()
    endforeach()
    set(vmxcsr_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_vmxcsr_lifted_o2.dll")
    add_custom_command(OUTPUT "${vmxcsr_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /EHsc /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_vmxcsr_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_vmxcsr_lifted_o2.obj" "/Fe${vmxcsr_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_vmxcsr_lifted.cpp" VERBATIM)
    add_custom_target(cpu_vmxcsr_lifted_o2 ALL DEPENDS "${vmxcsr_o2}")
    add_test(NAME cpu_aot_vmxcsr COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/vmxcsr.py"
        check translated "$<TARGET_FILE:cpu_mxcsr_harness>" "$<TARGET_FILE:cpu_vmxcsr>" "$<TARGET_FILE:cpu_vmxcsr_lifted>"
        ${vmxcsr_controls} "${vmxcsr_o2}")
    # The lowering alone refuses every malformed VEX load and store and lowers their well-formed neighbours.
    add_test(NAME cpu_aot_vmxcsr_malformed COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/vmxcsr.py"
        check malformed)
    add_test(NAME cpu_aot_vmxcsr_native COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/vmxcsr.py"
        check native "$<TARGET_FILE:cpu_mxcsr_harness>" "$<TARGET_FILE:cpu_vmxcsr>" "$<TARGET_FILE:cpu_vmxcsr_lifted>")
    set_tests_properties(cpu_aot_vmxcsr_native PROPERTIES SKIP_RETURN_CODE 77)
    # PF readers after the VEX scalar compares: the lifted DLL, the stale and reversed controls that must break a
    # rule, and an /O2 build. The MXCSR harness sets the masked MXCSR and reports whether VEX runs natively.
    cpu_asm_fixture(cpu_parity parity)
    set(parity_controls)
    foreach(variant IN ITEMS lifted stale reversed)
        set(parity_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_parity_${variant}.cpp")
        add_custom_command(OUTPUT "${parity_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/parity.py"
                emit "$<TARGET_FILE:cpu_parity>" "${parity_fixture}" ${variant}
            DEPENDS cpu_parity tests/cpu/parity.py tools/ffx_version_query.py tools/x87_lower.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_parity_${variant} SHARED "${parity_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND parity_controls "$<TARGET_FILE:cpu_parity_${variant}>")
        endif()
    endforeach()
    set(parity_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_parity_lifted_o2.dll")
    add_custom_command(OUTPUT "${parity_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /EHsc /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_parity_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_parity_lifted_o2.obj" "/Fe${parity_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_parity_lifted.cpp" VERBATIM)
    add_custom_target(cpu_parity_lifted_o2 ALL DEPENDS "${parity_o2}")
    add_test(NAME cpu_aot_parity COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/parity.py"
        check "$<TARGET_FILE:cpu_mxcsr_harness>" "$<TARGET_FILE:cpu_parity>" "$<TARGET_FILE:cpu_parity_lifted>"
        ${parity_controls} "${parity_o2}")
    # FTZ and DAZ in the profile's denormals opt-in: the lifted DLL, the sim variant that must keep every rule,
    # the noftz, nodaz and nomask controls that must break one, and an /O2 build of the translation.
    cpu_asm_fixture(cpu_mxcsr_denormals mxcsr_denormals)
    set(mxcsr_denormals_extras)
    foreach(variant IN ITEMS lifted noftz nodaz sim nomask)
        set(den_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_denormals_${variant}.cpp")
        add_custom_command(OUTPUT "${den_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/mxcsr_denormals.py"
                emit "$<TARGET_FILE:cpu_mxcsr_denormals>" "${den_fixture}" ${variant}
            DEPENDS cpu_mxcsr_denormals tests/cpu/mxcsr_denormals.py tools/ffx_version_query.py tools/x87_lower.py
                tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_mxcsr_denormals_${variant} SHARED "${den_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND mxcsr_denormals_extras "$<TARGET_FILE:cpu_mxcsr_denormals_${variant}>")
        endif()
    endforeach()
    set(den_o2 "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_denormals_lifted_o2.dll")
    add_custom_command(OUTPUT "${den_o2}"
        COMMAND "${CMAKE_CXX_COMPILER}" /nologo /O2 /W4 /EHsc /LD "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_denormals_lifted.cpp"
            "/Fo${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_denormals_lifted_o2.obj" "/Fe${den_o2}"
        DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/cpu_mxcsr_denormals_lifted.cpp" VERBATIM)
    add_custom_target(cpu_mxcsr_denormals_lifted_o2 ALL DEPENDS "${den_o2}")
    add_test(NAME cpu_aot_mxcsr_denormals COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/mxcsr_denormals.py"
        check-ftz "$<TARGET_FILE:cpu_mxcsr_harness>" "$<TARGET_FILE:cpu_mxcsr_denormals>"
        "$<TARGET_FILE:cpu_mxcsr_denormals_lifted>" ${mxcsr_denormals_extras} "${den_o2}")
    add_test(NAME cpu_aot_mxcsr_denormals_daz COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/mxcsr_denormals.py"
        check-daz "$<TARGET_FILE:cpu_mxcsr_harness>" "$<TARGET_FILE:cpu_mxcsr_denormals>"
        "$<TARGET_FILE:cpu_mxcsr_denormals_lifted>" ${mxcsr_denormals_extras} "${den_o2}")
    set_tests_properties(cpu_aot_mxcsr_denormals_daz PROPERTIES SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_destroy destroy)
    target_link_libraries(cpu_destroy PRIVATE ucrt.lib)
    cpu_translation(cpu_destroy cpu_chained_aot release_context FFX_DESTROY)
    add_library(cpu_destroy_provider SHARED tests/cpu/destroy_provider.cpp)
    cpu_asm_fixture(cpu_x87_harness x87_harness)
    cpu_asm_fixture(cpu_x87_add x87_add)
    # The lifted DLL and six mutated controls that the check requires to mismatch.
    set(x87_add_controls pc64 double m80double nosticky nanorder signedzero)
    set(x87_add_control_files "")
    set(cpu_x87_add_variants lifted ${x87_add_controls})
    x2w_emit_variants(x87_add cpu_x87_add "${cpu_x87_add_variants}"
        tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py
        tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_add_variants)
        set(x87_add_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_add_${variant}.cpp")
        add_library(cpu_x87_add_${variant} SHARED "${x87_add_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_add_control_files "$<TARGET_FILE:cpu_x87_add_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_add COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_add.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_add>"
        "$<TARGET_FILE:cpu_x87_add_lifted>" ${x87_add_control_files})
    cpu_asm_fixture(cpu_x87_mul x87_mul)
    # The lifted DLL and six mutated controls that the check requires to mismatch.
    set(x87_mul_control_files "")
    set(cpu_x87_mul_variants lifted pc64 double nolow sign infzero memquiet)
    x2w_emit_variants(x87_mul cpu_x87_mul "${cpu_x87_mul_variants}"
        tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
        tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_mul_variants)
        set(x87_mul_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_mul_${variant}.cpp")
        add_library(cpu_x87_mul_${variant} SHARED "${x87_mul_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_mul_control_files "$<TARGET_FILE:cpu_x87_mul_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_mul COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_mul.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_mul>"
        "$<TARGET_FILE:cpu_x87_mul_lifted>" ${x87_mul_control_files})
    cpu_asm_fixture(cpu_x87_div x87_div)
    # The lifted DLL and seven mutated controls that the check requires to mismatch.
    set(x87_div_control_files "")
    set(cpu_x87_div_variants lifted pc64 double nosticky divzero reverse zerosign memquiet)
    x2w_emit_variants(x87_div cpu_x87_div "${cpu_x87_div_variants}"
        tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py
        tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_div_variants)
        set(x87_div_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_div_${variant}.cpp")
        add_library(cpu_x87_div_${variant} SHARED "${x87_div_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_div_control_files "$<TARGET_FILE:cpu_x87_div_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_div COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_div.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_div>"
        "$<TARGET_FILE:cpu_x87_div_lifted>" ${x87_div_control_files})
    cpu_asm_fixture(cpu_x87_sub x87_sub)
    # The lifted DLL and seven mutated controls that the check requires to mismatch.
    set(x87_sub_control_files "")
    set(cpu_x87_sub_variants lifted pc64 double nansign reverse cancel nosticky memquiet)
    x2w_emit_variants(x87_sub cpu_x87_sub "${cpu_x87_sub_variants}"
        tests/cpu/x87_div.py tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py
        tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_sub_variants)
        set(x87_sub_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_sub_${variant}.cpp")
        add_library(cpu_x87_sub_${variant} SHARED "${x87_sub_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_sub_control_files "$<TARGET_FILE:cpu_x87_sub_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_sub COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_sub.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_sub>"
        "$<TARGET_FILE:cpu_x87_sub_lifted>" ${x87_sub_control_files})
    cpu_asm_fixture(cpu_x87_moves x87_moves)
    # The lifted DLL and seven mutated controls that the check requires to mismatch.
    set(x87_moves_control_files "")
    set(cpu_x87_moves_variants lifted chssub absnan fxchnone fldtop fstpdrop fstwrite copyquiet)
    x2w_emit_variants(x87_moves cpu_x87_moves "${cpu_x87_moves_variants}"
        tests/cpu/x87_sub.py tests/cpu/x87_div.py tests/cpu/x87_mul.py tests/cpu/x87_add.py
        tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py
        tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_moves_variants)
        set(x87_moves_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_moves_${variant}.cpp")
        add_library(cpu_x87_moves_${variant} SHARED "${x87_moves_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_moves_control_files "$<TARGET_FILE:cpu_x87_moves_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_moves COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_moves.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_moves>"
        "$<TARGET_FILE:cpu_x87_moves_lifted>" ${x87_moves_control_files})
    cpu_asm_fixture(cpu_x87_constants x87_constants)
    # The lifted DLL and four mutated controls that the check requires to mismatch.
    set(x87_constants_control_files "")
    set(cpu_x87_constants_variants lifted pc53 chop fldzneg swaplogs)
    x2w_emit_variants(x87_constants cpu_x87_constants "${cpu_x87_constants_variants}"
        tests/cpu/x87_moves.py tests/cpu/x87_sub.py tests/cpu/x87_div.py tests/cpu/x87_mul.py
        tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
        tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_constants_variants)
        set(x87_constants_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_constants_${variant}.cpp")
        add_library(cpu_x87_constants_${variant} SHARED "${x87_constants_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_constants_control_files "$<TARGET_FILE:cpu_x87_constants_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_constants COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_constants.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_constants>"
        "$<TARGET_FILE:cpu_x87_constants_lifted>" ${x87_constants_control_files})
    cpu_asm_fixture(cpu_x87_integers x87_integers)
    # The lifted DLL and six mutated controls that the check requires to mismatch.
    set(x87_integers_control_files "")
    set(cpu_x87_integers_variants lifted chopall roundtt saturate nanzero zext fild53)
    x2w_emit_variants(x87_integers cpu_x87_integers "${cpu_x87_integers_variants}"
        tests/cpu/x87_moves.py tests/cpu/x87_sub.py tests/cpu/x87_div.py tests/cpu/x87_mul.py
        tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
        tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_integers_variants)
        set(x87_integers_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_integers_${variant}.cpp")
        add_library(cpu_x87_integers_${variant} SHARED "${x87_integers_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_integers_control_files "$<TARGET_FILE:cpu_x87_integers_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_integers COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_integers.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_integers>"
        "$<TARGET_FILE:cpu_x87_integers_lifted>" ${x87_integers_control_files})
    cpu_asm_fixture(cpu_x87_compare x87_compare)
    # The lifted DLL and seven mutated controls that the check requires to mismatch.
    set(x87_compare_control_files "")
    set(cpu_x87_compare_variants lifted unordeq swap zeroorder low11 rawexp unnormal keepof)
    x2w_emit_variants(x87_compare cpu_x87_compare "${cpu_x87_compare_variants}"
        tests/cpu/x87_moves.py tests/cpu/x87_sub.py tests/cpu/adx.py tests/cpu/x87_div.py
        tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py
        tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_compare_variants)
        set(x87_compare_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_compare_${variant}.cpp")
        add_library(cpu_x87_compare_${variant} SHARED "${x87_compare_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_compare_control_files "$<TARGET_FILE:cpu_x87_compare_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_compare COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_compare.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_compare>"
        "$<TARGET_FILE:cpu_x87_compare_lifted>" ${x87_compare_control_files})
    # Skips (77) after every other check when the host lacks ADX for the native ADOX export.
    set_tests_properties(cpu_aot_x87_compare PROPERTIES SKIP_RETURN_CODE 77)
    cpu_asm_fixture(cpu_x87_sqrt x87_sqrt)
    # The lifted DLL and six mutated controls that the check requires to mismatch.
    set(x87_sqrt_control_files "")
    set(cpu_x87_sqrt_variants lifted pc64 double nosticky negzero negabs snan)
    x2w_emit_variants(x87_sqrt cpu_x87_sqrt "${cpu_x87_sqrt_variants}"
        tests/cpu/x87_moves.py tests/cpu/x87_sub.py tests/cpu/x87_div.py tests/cpu/x87_mul.py
        tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
        tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_sqrt_variants)
        set(x87_sqrt_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_sqrt_${variant}.cpp")
        add_library(cpu_x87_sqrt_${variant} SHARED "${x87_sqrt_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_sqrt_control_files "$<TARGET_FILE:cpu_x87_sqrt_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_sqrt COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_sqrt.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_sqrt>"
        "$<TARGET_FILE:cpu_x87_sqrt_lifted>" ${x87_sqrt_control_files})
    cpu_asm_fixture(cpu_x87_rndint x87_rndint)
    # The lifted DLL and five mutated controls that the check requires to mismatch.
    set(x87_rndint_control_files "")
    set(cpu_x87_rndint_variants lifted chop tiesaway zerosign trunc53 snan)
    x2w_emit_variants(x87_rndint cpu_x87_rndint "${cpu_x87_rndint_variants}"
        tests/cpu/x87_integers.py tests/cpu/x87_moves.py tests/cpu/x87_sub.py tests/cpu/x87_div.py
        tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py
        tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_rndint_variants)
        set(x87_rndint_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_rndint_${variant}.cpp")
        add_library(cpu_x87_rndint_${variant} SHARED "${x87_rndint_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_rndint_control_files "$<TARGET_FILE:cpu_x87_rndint_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_rndint COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_rndint.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_rndint>"
        "$<TARGET_FILE:cpu_x87_rndint_lifted>" ${x87_rndint_control_files})
    cpu_asm_fixture(cpu_x87_xtract x87_xtract)
    # The lifted DLL and six mutated controls that the check requires to mismatch.
    set(x87_xtract_control_files "")
    set(cpu_x87_xtract_variants lifted zeroexp denormal biased unsigned snan order)
    x2w_emit_variants(x87_xtract cpu_x87_xtract "${cpu_x87_xtract_variants}"
        tests/cpu/x87_integers.py tests/cpu/x87_moves.py tests/cpu/x87_sub.py tests/cpu/x87_div.py
        tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py
        tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_xtract_variants)
        set(x87_xtract_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_xtract_${variant}.cpp")
        add_library(cpu_x87_xtract_${variant} SHARED "${x87_xtract_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_xtract_control_files "$<TARGET_FILE:cpu_x87_xtract_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_xtract COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_xtract.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_xtract>"
        "$<TARGET_FILE:cpu_x87_xtract_lifted>" ${x87_xtract_control_files})
    cpu_asm_fixture(cpu_x87_scale x87_scale)
    # The lifted DLL and six mutated controls that the check requires to mismatch.
    set(x87_scale_control_files "")
    set(cpu_x87_scale_variants lifted pc53 chop floor neginf zeroinf swap)
    x2w_emit_variants(x87_scale cpu_x87_scale "${cpu_x87_scale_variants}"
        tests/cpu/x87_xtract.py tests/cpu/x87_integers.py tests/cpu/x87_moves.py tests/cpu/x87_sub.py
        tests/cpu/x87_div.py tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py
        tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_scale_variants)
        set(x87_scale_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_scale_${variant}.cpp")
        add_library(cpu_x87_scale_${variant} SHARED "${x87_scale_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_scale_control_files "$<TARGET_FILE:cpu_x87_scale_${variant}>")
        endif()
    endforeach()
    x2w_add_check_part(cpu_aot_x87_scale native "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_scale.py"
        check-native "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_scale>")
    x2w_add_check_part(cpu_aot_x87_scale lifted "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_scale.py"
        check-lifted "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_scale_lifted>")
    x2w_add_check_part(cpu_aot_x87_scale controls "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_scale.py"
        check-controls "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_scale>" ${x87_scale_control_files})
    add_test(NAME cpu_aot_x87_scale COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_scale.py"
        check-rejections)
    x2w_require_check_parts(cpu_aot_x87_scale native lifted controls)
    cpu_asm_fixture(cpu_x87_fcmov x87_fcmov)
    # The lifted DLL and eight mutated controls that the check requires to mismatch.
    set(x87_fcmov_control_files "")
    set(cpu_x87_fcmov_variants lifted invert beonly nbeor neverne always quiet cmcdrop nocarryin)
    x2w_emit_variants(x87_fcmov cpu_x87_fcmov "${cpu_x87_fcmov_variants}"
        tests/cpu/x87_compare.py tests/cpu/x87_integers.py tests/cpu/x87_moves.py tests/cpu/x87_sub.py
        tests/cpu/x87_div.py tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py
        tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_fcmov_variants)
        set(x87_fcmov_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_fcmov_${variant}.cpp")
        add_library(cpu_x87_fcmov_${variant} SHARED "${x87_fcmov_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_fcmov_control_files "$<TARGET_FILE:cpu_x87_fcmov_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_fcmov COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_fcmov.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_fcmov>"
        "$<TARGET_FILE:cpu_x87_fcmov_lifted>" ${x87_fcmov_control_files})
    cpu_asm_fixture(cpu_x87_iarith x87_iarith)
    # The lifted DLL and six mutated controls that the check requires to mismatch.
    set(x87_iarith_control_files "")
    set(cpu_x87_iarith_variants lifted subrev divrev zext16 zext32 wide16 pc64)
    x2w_emit_variants(x87_iarith cpu_x87_iarith "${cpu_x87_iarith_variants}"
        tests/cpu/x87_integers.py tests/cpu/x87_moves.py tests/cpu/x87_sub.py tests/cpu/x87_div.py
        tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py
        tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_iarith_variants)
        set(x87_iarith_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_iarith_${variant}.cpp")
        add_library(cpu_x87_iarith_${variant} SHARED "${x87_iarith_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_iarith_control_files "$<TARGET_FILE:cpu_x87_iarith_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_iarith COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_iarith.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_iarith>"
        "$<TARGET_FILE:cpu_x87_iarith_lifted>" ${x87_iarith_control_files})
    cpu_asm_fixture(cpu_x87_fnstcw x87_fnstcw)
    # The lifted DLL and four mutated controls that the check requires to mismatch.
    set(x87_fnstcw_control_files "")
    set(cpu_x87_fnstcw_variants lifted fninit wide skip lowbyte)
    x2w_emit_variants(x87_fnstcw cpu_x87_fnstcw "${cpu_x87_fnstcw_variants}"
        tests/cpu/x87_div.py tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py
        tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_fnstcw_variants)
        set(x87_fnstcw_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_fnstcw_${variant}.cpp")
        add_library(cpu_x87_fnstcw_${variant} SHARED "${x87_fnstcw_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_fnstcw_control_files "$<TARGET_FILE:cpu_x87_fnstcw_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_fnstcw COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_fnstcw.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_fnstcw>"
        "$<TARGET_FILE:cpu_x87_fnstcw_lifted>" ${x87_fnstcw_control_files})
    cpu_asm_fixture(cpu_x87_examine x87_examine)
    # The lifted DLL and eleven mutated controls that the check requires to mismatch.
    set(x87_examine_control_files "")
    set(cpu_x87_examine_variants lifted normal unsigned positive legacy ffreep fftop ffree freetop fstsw nopop twopop)
    x2w_emit_variants(x87_examine cpu_x87_examine "${cpu_x87_examine_variants}"
        tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
        tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_examine_variants)
        set(x87_examine_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_examine_${variant}.cpp")
        add_library(cpu_x87_examine_${variant} SHARED "${x87_examine_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_examine_control_files "$<TARGET_FILE:cpu_x87_examine_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_examine COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_examine.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_examine>"
        "$<TARGET_FILE:cpu_x87_examine_lifted>" ${x87_examine_control_files})
    cpu_asm_fixture(cpu_x87_fprem x87_fprem)
    # The lifted DLL and eight mutated controls that the check requires to mismatch.
    set(x87_fprem_control_files "")
    set(cpu_x87_fprem_variants lifted nopartial nonan d63 truncate1 tieup halfnear qswap zerosign)
    x2w_emit_variants(x87_fprem cpu_x87_fprem "${cpu_x87_fprem_variants}"
        tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
        tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_fprem_variants)
        set(x87_fprem_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_fprem_${variant}.cpp")
        add_library(cpu_x87_fprem_${variant} SHARED "${x87_fprem_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_fprem_control_files "$<TARGET_FILE:cpu_x87_fprem_${variant}>")
        endif()
    endforeach()
    x2w_add_check_part(cpu_aot_x87_fprem lifted "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_fprem.py"
        check-lifted "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_fprem_lifted>")
    x2w_add_check_part(cpu_aot_x87_fprem native "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_fprem.py"
        check-native "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_fprem>")
    x2w_add_check_part(cpu_aot_x87_fprem controls "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_fprem.py"
        check-controls "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_fprem>" ${x87_fprem_control_files})
    add_test(NAME cpu_aot_x87_fprem COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_fprem.py"
        check-light)
    x2w_require_check_parts(cpu_aot_x87_fprem lifted native controls)
    cpu_asm_fixture(cpu_x87_fldcw x87_fldcw)
    # The checked translation and seventeen mutated controls that the check requires to mismatch.
    set(x87_fldcw_control_files "")
    set(cpu_x87_fldcw_variants lifted rcnearest pc53 fistnearest constnearest rawword nounmasked pc01 noreturn onereturn fninitword fninitsw deferred swtop swbyte swwide swaddr swnone)
    x2w_emit_variants(x87_fldcw cpu_x87_fldcw "${cpu_x87_fldcw_variants}"
        tests/cpu/x87_add.py tests/cpu/x87_constants.py tests/cpu/x87_div.py tests/cpu/x87_integers.py
        tests/cpu/x87_moves.py tests/cpu/x87_mul.py tests/cpu/x87_rndint.py tests/cpu/x87_scale.py
        tests/cpu/x87_sqrt.py tests/cpu/x87_sub.py tests/cpu/x87_xtract.py tools/ffx_version_query.py
        tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_fldcw_variants)
        set(x87_fldcw_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_fldcw_${variant}.cpp")
        add_library(cpu_x87_fldcw_${variant} SHARED "${x87_fldcw_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_fldcw_control_files "$<TARGET_FILE:cpu_x87_fldcw_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_fldcw COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_fldcw.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_fldcw>"
        "$<TARGET_FILE:cpu_x87_fldcw_lifted>" ${x87_fldcw_control_files})
    cpu_asm_fixture(cpu_x87_status x87_status)
    # The lifted DLL and seven mutated controls that the check requires to mismatch.
    set(x87_status_control_files "")
    set(cpu_x87_status_variants lifted c2drop c0c3 top0 sahfpf oddparity andparity fcomiclear)
    x2w_emit_variants(x87_status cpu_x87_status "${cpu_x87_status_variants}"
        tests/cpu/x87_compare.py tests/cpu/x87_moves.py tests/cpu/x87_div.py tests/cpu/x87_mul.py
        tests/cpu/x87_sub.py tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py
        tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_status_variants)
        set(x87_status_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_status_${variant}.cpp")
        add_library(cpu_x87_status_${variant} SHARED "${x87_status_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_status_control_files "$<TARGET_FILE:cpu_x87_status_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_status COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_status.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_status>"
        "$<TARGET_FILE:cpu_x87_status_lifted>" ${x87_status_control_files})
    # FNSTENV and FNSAVE after FNINIT, and the FSTENV and FSAVE forms the translation refuses: pure Python.
    add_test(NAME cpu_x87_environment_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/x87_environment_check.py")
    cpu_asm_fixture(cpu_x87_parity x87_parity)
    # The lifted DLL and five mutated controls that the check requires to mismatch.
    set(x87_parity_control_files "")
    set(cpu_x87_parity_variants lifted pfnever pfequal pfkeep uinvert nuinvert)
    x2w_emit_variants(x87_parity cpu_x87_parity "${cpu_x87_parity_variants}"
        tests/cpu/x87_status.py tests/cpu/x87_compare.py tests/cpu/x87_moves.py tests/cpu/x87_div.py
        tests/cpu/x87_mul.py tests/cpu/x87_sub.py tests/cpu/x87_add.py tools/ffx_version_query.py
        tools/x87_lower.py tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_parity_variants)
        set(x87_parity_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_parity_${variant}.cpp")
        add_library(cpu_x87_parity_${variant} SHARED "${x87_parity_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_parity_control_files "$<TARGET_FILE:cpu_x87_parity_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_parity COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_parity.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_parity>"
        "$<TARGET_FILE:cpu_x87_parity_lifted>" ${x87_parity_control_files})
    cpu_asm_fixture(cpu_x87_bcd x87_bcd)
    # The lifted DLL and nine mutated controls that the check requires to mismatch.
    set(x87_bcd_control_files "")
    set(cpu_x87_bcd_variants lifted rcnearest rangebefore threshold zerosign indefinite bstpnibbles bldnibbles signbits nodigitcheck)
    x2w_emit_variants(x87_bcd cpu_x87_bcd "${cpu_x87_bcd_variants}"
        tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py tools/x87_soft.h
        tools/cpu_ranges.py tools/cpu_leaf_aot.py)
    foreach(variant IN LISTS cpu_x87_bcd_variants)
        set(x87_bcd_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_bcd_${variant}.cpp")
        add_library(cpu_x87_bcd_${variant} SHARED "${x87_bcd_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_bcd_control_files "$<TARGET_FILE:cpu_x87_bcd_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_bcd COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_bcd.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_bcd>"
        "$<TARGET_FILE:cpu_x87_bcd_lifted>" ${x87_bcd_control_files})
    cpu_asm_fixture(cpu_x87_trig x87_trig)
    # The lifted DLL and eight mutated controls that the check requires to mismatch.
    set(x87_trig_control_files "")
    foreach(variant IN ITEMS lifted noc2 c262 sincosswap ptanno1 patanswap sinnegzero snan pc53)
        set(x87_trig_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_x87_trig_${variant}.cpp")
        add_custom_command(OUTPUT "${x87_trig_fixture}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_trig.py"
                emit "$<TARGET_FILE:cpu_x87_trig>" "${x87_trig_fixture}" ${variant}
            DEPENDS cpu_x87_trig tests/cpu/x87_trig.py tests/cpu/x87_moves.py tests/cpu/x87_div.py
                tests/cpu/x87_mul.py tests/cpu/x87_add.py tools/ffx_version_query.py tools/x87_lower.py
                tools/x87_soft.h tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
        add_library(cpu_x87_trig_${variant} SHARED "${x87_trig_fixture}")
        if(NOT variant STREQUAL "lifted")
            list(APPEND x87_trig_control_files "$<TARGET_FILE:cpu_x87_trig_${variant}>")
        endif()
    endforeach()
    add_test(NAME cpu_aot_x87_trig COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/x87_trig.py"
        check "$<TARGET_FILE:cpu_x87_harness>" "$<TARGET_FILE:cpu_x87_trig>"
        "$<TARGET_FILE:cpu_x87_trig_lifted>" ${x87_trig_control_files})
    set(cpu_x87_exp_log_aot_exports
        "op_f2xm1_m80,op_f2xm1_m64,op_f2xm1_m32,op_f2xm1_fst_m64,op_f2xm1_fst_m32,op_f2xm1_sw,"
        "op_fyl2x_m80,op_fyl2x_m64,op_fyl2x_m32,op_fyl2x_sw,op_fyl2x_pop_depth,op_fyl2x_depth8,"
        "op_fyl2xp1_m80,op_fyl2xp1_m64,op_fyl2xp1_m32,op_fyl2xp1_sw,op_fyl2xp1_pop_depth,"
        "op_exp_log_roundtrip,op_fcw_roundtrip,op_fninit_cw_sw,op_fninit_sw")
    string(CONCAT cpu_x87_exp_log_aot_exports ${cpu_x87_exp_log_aot_exports})
    foreach(variant IN ITEMS original altered)
        cpu_asm_fixture(cpu_x87_exp_log_aot_${variant} x87_exp_log_aot)
        cpu_translation(cpu_x87_exp_log_aot_${variant} cpu_x87_exp_log_aot "${cpu_x87_exp_log_aot_exports}")
    endforeach()
    target_compile_definitions(cpu_x87_exp_log_aot_altered PRIVATE ALTER_X87_EXP_LOG)
    add_test(NAME cpu_aot_x87_exp_log COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/x87_exp_log_aot_check.py"
        "$<TARGET_FILE:cpu_x87_exp_log_aot_original>"
        "$<TARGET_FILE:cpu_x87_exp_log_aot_original_lifted>"
        "$<TARGET_FILE:cpu_x87_exp_log_aot_altered>"
        "$<TARGET_FILE:cpu_x87_exp_log_aot_altered_lifted>")
    set_tests_properties(cpu_aot_x87_exp_log PROPERTIES
        ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/cpu_aot_x87_exp_log.txt")
    cpu_asm_fixture(cpu_create create_context)
    set(create_fixture "${CMAKE_CURRENT_BINARY_DIR}/cpu_create_lifted.cpp")
    add_custom_command(OUTPUT "${create_fixture}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/cpu/create_fixture.py"
            "$<TARGET_FILE:cpu_create>" "${create_fixture}"
        DEPENDS cpu_create tests/cpu/create_fixture.py tools/ffx_create_context.py
            tools/ffx_version_query.py tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
    add_library(cpu_create_lifted SHARED "${create_fixture}")
    add_test(NAME cpu_aot_context_lifecycle COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/context_lifecycle.py" "$<TARGET_FILE:cpu_create>"
        "$<TARGET_FILE:cpu_create_lifted>" "$<TARGET_FILE:cpu_destroy_lifted>")
    add_test(NAME cpu_aot_destroy_contract COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/destroy_check.py" "$<TARGET_FILE:cpu_destroy>"
        "$<TARGET_FILE:cpu_destroy_lifted>" "$<TARGET_FILE:cpu_destroy_provider>")
    add_test(NAME cpu_aot_object_callback COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/callback_check.py" "$<TARGET_FILE:cpu_callback>"
        "$<TARGET_FILE:cpu_callback_lifted>")
    add_test(NAME cpu_aot_chained_ranges COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/chained_check.py" "$<TARGET_FILE:cpu_chained>"
        "$<TARGET_FILE:cpu_chained_lifted>" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_chained_jne>" "$<TARGET_FILE:cpu_chained_jne_lifted>"
        "$<TARGET_FILE:cpu_chained_zero>" "$<TARGET_FILE:cpu_chained_zero_lifted>"
        "$<TARGET_FILE:cpu_chained_imm>" "$<TARGET_FILE:cpu_chained_imm_lifted>"
        "$<TARGET_FILE:cpu_chained_frame>" "$<TARGET_FILE:cpu_chained_frame_lifted>")
    add_test(NAME cpu_aot_chained_dead_reads COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/chained_dead_read_check.py" "$<TARGET_FILE:cpu_guarded_call>"
        "$<TARGET_FILE:cpu_chained_dead_read>" ${chained_dead_read_files})
    add_test(NAME cpu_aot_direct_call COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/direct_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_call_original>" "$<TARGET_FILE:cpu_call_original_lifted>"
        "$<TARGET_FILE:cpu_call_altered_lifted>")
    add_test(NAME cpu_aot_call_pair COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/call_pair_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_pair_original>" "$<TARGET_FILE:cpu_pair_swapped>"
        "$<TARGET_FILE:cpu_pair_original_lifted>" "$<TARGET_FILE:cpu_pair_swapped_lifted>"
        "$<TARGET_FILE:cpu_pair_first_lifted>" "$<TARGET_FILE:cpu_pair_second_lifted>")
    foreach(kind IN ITEMS named ordinal)
        if(kind STREQUAL "named")
            set(prefix cpu_import)
            set(contract SYMBOL mix_args)
        else()
            set(prefix cpu_ordinal)
            set(contract SYMBOL "#77" LINK_NAME mix_args)
        endif()
        foreach(variant IN ITEMS provider altered)
            add_library(${prefix}_${variant} SHARED tests/cpu/import_provider.cpp tests/cpu/${kind}_provider.def)
        endforeach()
        target_compile_definitions(${prefix}_altered PRIVATE ALTER_RETURN)
        cpu_asm_fixture(${prefix}_original direct import)
        target_compile_definitions(${prefix}_original PRIVATE IMPORT_MIX)
        target_link_libraries(${prefix}_original PRIVATE ${prefix}_provider)
        cpu_translation(${prefix}_original cpu_call_aot call_mix PROVIDER ${prefix}_provider ${contract})
        target_link_options(${prefix}_original_lifted PRIVATE /INCREMENTAL:NO)
    endforeach()
    cpu_asm_fixture(cpu_repeat_import repeat_call repeat_import)
    target_compile_definitions(cpu_repeat_import PRIVATE IMPORT_MIX)
    target_link_libraries(cpu_repeat_import PRIVATE cpu_import_provider)
    cpu_translation(cpu_repeat_import cpu_call_aot call_twice PROVIDER cpu_import_provider SYMBOL mix_args)
    target_link_options(cpu_repeat_import_lifted PRIVATE /INCREMENTAL:NO)
    add_test(NAME cpu_aot_repeated_call COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/repeat_call_check.py" "$<TARGET_FILE:cpu_register_probe>"
        "$<TARGET_FILE:cpu_repeat_original>" "$<TARGET_FILE:cpu_repeat_original_lifted>"
        "$<TARGET_FILE:cpu_repeat_altered_lifted>" "$<TARGET_FILE:cpu_repeat_dropped>"
        "$<TARGET_FILE:cpu_repeat_import>" "$<TARGET_FILE:cpu_repeat_import_lifted>")
    add_test(NAME cpu_aot_import_call COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/import_check.py" "$<TARGET_FILE:cpu_import_original>"
        "$<TARGET_FILE:cpu_import_original_lifted>" "$<TARGET_FILE:cpu_import_provider>"
        "$<TARGET_FILE:cpu_import_altered>" "$<TARGET_FILE:cpu_register_probe>")
    add_library(cpu_exe_io SHARED tests/cpu/exe_io.cpp)
    # Use Zig's normal single-threaded console startup, including RtlExitUserProcess.
    enable_language(C)
    set(archive_src "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/archive")
    # Keep the scalar reference PE identical across the Debug and /O2 host builds.
    set(blast_obj "${CMAKE_CURRENT_BINARY_DIR}/blast_scalar.obj")
    add_custom_command(OUTPUT "${blast_obj}"
        COMMAND "${CMAKE_C_COMPILER}" /nologo /c /MD /Od /GS- /Gs65536 /Zl "/Fo${blast_obj}" "${archive_src}/blast/blast.c"
        DEPENDS "${archive_src}/blast/blast.c" "${archive_src}/blast/blast.h" VERBATIM)
    add_library(blast_source SHARED "${blast_obj}" "${archive_src}/blast.def")
    set_target_properties(blast_source PROPERTIES LINKER_LANGUAGE C)
    target_link_options(blast_source PRIVATE /NOENTRY /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(blast_source PRIVATE msvcrt ucrt vcruntime)

    set(blast_cpp "${CMAKE_CURRENT_BINARY_DIR}/blast_lifted.cpp")
    add_custom_command(OUTPUT "${blast_cpp}"
        COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/tools"
            "${INTAKE_PYTHON}" -B "${archive_src}/translate_blast.py" "$<TARGET_FILE:blast_source>" "${blast_cpp}"
        DEPENDS blast_source "${archive_src}/translate_blast.py" "${archive_src}/blast_runtime.hpp"
            tools/cpu_switch_aot.py tools/cpu_ranges.py tools/cpu_leaf_aot.py VERBATIM)
    add_library(blast_lifted SHARED "${blast_cpp}" "${archive_src}/blast.def")
    target_include_directories(blast_lifted PRIVATE "${archive_src}")

    add_library(archive_codec_lifted SHARED "${archive_src}/codec.cpp" "${archive_src}/texture_stdout.cpp")
    target_link_libraries(archive_codec_lifted PRIVATE blast_lifted)
    set_target_properties(archive_codec_lifted PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
    add_library(archive_codec SHARED "${archive_src}/codec.cpp" "${archive_src}/texture_stdout.cpp")
    target_link_libraries(archive_codec PRIVATE blast_source)
    set_target_properties(archive_codec PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
    function(build_archive_reader entry exe cpp provider translator)
        cmake_parse_arguments(READER "EXPORT_SYMBOLS" "" "" ${ARGN})
        set(export_flags)
        if(READER_EXPORT_SYMBOLS)
            # Publish the directory lookup's leaf entry for the function-boundary verifier.
            set(export_flags -rdynamic)
        endif()
        add_custom_command(OUTPUT "${exe}"
            COMMAND "${INTAKE_PYTHON}" -m ziglang build-exe "${entry}"
                "-L$<TARGET_LINKER_FILE_DIR:${provider}>" -target x86_64-windows-gnu
                -O ReleaseSmall -fsingle-threaded -funwind-tables ${export_flags} "-femit-bin=${exe}"
            DEPENDS ${provider} "${entry}" ${READER_UNPARSED_ARGUMENTS} VERBATIM)
        add_custom_command(OUTPUT "${cpp}"
            COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/tools"
                "${INTAKE_PYTHON}" -B "${archive_src}/${translator}" "${exe}" "${cpp}"
            DEPENDS "${exe}" "${archive_src}/${translator}" tools/cpu_stdio_exe_aot.py
                tools/cpu_switch_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
    endfunction()
    set(archive_exe "${CMAKE_CURRENT_BINARY_DIR}/archive_reader.exe")
    set(archive_cpp "${CMAKE_CURRENT_BINARY_DIR}/archive_reader_lifted.cpp")
    build_archive_reader("${archive_src}/reader.zig" "${archive_exe}" "${archive_cpp}" archive_codec translate_reader.py)
    add_executable(archive_reader_lifted "${archive_cpp}")
    target_link_libraries(archive_reader_lifted PRIVATE archive_codec ntdll)
    add_test(NAME cpu_native_archive_reader COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/archive_check.py" "$<TARGET_FILE:pe_map>"
        "${archive_exe}" "$<TARGET_FILE:archive_reader_lifted>" "$<TARGET_FILE:archive_codec>")

    add_executable(archive_all_lifted "${archive_cpp}")
    target_link_libraries(archive_all_lifted PRIVATE archive_codec_lifted ntdll)
    add_test(NAME cpu_native_archive_blast COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/archive_check.py" "$<TARGET_FILE:pe_map>"
        "${archive_exe}" "$<TARGET_FILE:archive_all_lifted>" "$<TARGET_FILE:archive_codec>"
        "$<TARGET_FILE:blast_source>" "$<TARGET_FILE:blast_lifted>" "$<TARGET_FILE:archive_codec_lifted>")
    # 77: Control Flow Guard enforced for the pe_map runner, whose blast longjmp cases then cannot run (#1293).
    set_tests_properties(cpu_native_archive_blast PROPERTIES SKIP_RETURN_CODE 77)

    set(texture_exe "${CMAKE_CURRENT_BINARY_DIR}/archive_texture_reader.exe")
    set(texture_cpp "${CMAKE_CURRENT_BINARY_DIR}/archive_texture_reader_lifted.cpp")
    build_archive_reader("${archive_src}/texture_reader.zig" "${texture_exe}" "${texture_cpp}" archive_codec translate_reader.py
        "${archive_src}/reader.zig")
    add_executable(archive_texture_lifted "${texture_cpp}")
    target_link_libraries(archive_texture_lifted PRIVATE archive_codec_lifted ntdll)
    add_test(NAME cpu_archive_texture_publication COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/archive_texture_check.py" "$<TARGET_FILE:pe_map>"
        "${texture_exe}" "$<TARGET_FILE:archive_texture_lifted>" "$<TARGET_FILE:archive_codec>"
        "$<TARGET_FILE:blast_source>")
    # 77: Control Flow Guard enforced for the pe_map runner, whose blast longjmp cases then cannot run (#1293).
    set_tests_properties(cpu_archive_texture_publication PROPERTIES SKIP_RETURN_CODE 77)

    # The same reader image drawing each completed record through D3D12 (#830). The GPU codec keeps
    # the name archive_codec.dll in its own directory, next to copies of the reader and blast.
    set(archive_gpu_dir "${CMAKE_CURRENT_BINARY_DIR}/archive_gpu")
    # The native reader runs from this folder; give it the same app-local WARP as the lifted EXE.
    offscreen_app_local_warp("${OFFSCREEN_WARP_DIR}" "${archive_gpu_dir}")
    set(archive_gpu_sources "${archive_src}/codec.cpp" "${archive_src}/texture_gpu.cpp"
        "${archive_src}/quad_frames.cpp" "${CMAKE_CURRENT_BINARY_DIR}/tex_quad_vs.h"
        "${CMAKE_CURRENT_BINARY_DIR}/tex_quad_ps.h")
    add_library(archive_codec_gpu SHARED ${archive_gpu_sources})
    target_link_libraries(archive_codec_gpu PRIVATE blast_source dxgi d3d12)
    set_target_properties(archive_codec_gpu PROPERTIES OUTPUT_NAME archive_codec
        RUNTIME_OUTPUT_DIRECTORY "${archive_gpu_dir}" ARCHIVE_OUTPUT_DIRECTORY "${archive_gpu_dir}")
    add_library(archive_codec_gpu_lifted SHARED ${archive_gpu_sources})
    target_link_libraries(archive_codec_gpu_lifted PRIVATE blast_lifted dxgi d3d12)
    foreach(codec IN ITEMS archive_codec_gpu archive_codec_gpu_lifted)
        target_include_directories(${codec} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
        target_compile_features(${codec} PRIVATE cxx_std_17)
        set_target_properties(${codec} PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
    endforeach()
    set(archive_gpu_reader "${archive_gpu_dir}/archive_texture_reader.exe")
    add_custom_command(OUTPUT "${archive_gpu_reader}" "${archive_gpu_dir}/blast_source.dll"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different "${texture_exe}" "$<TARGET_FILE:blast_source>"
            "${archive_gpu_dir}"
        DEPENDS "${texture_exe}" blast_source VERBATIM)
    add_custom_target(archive_gpu_reader ALL DEPENDS "${archive_gpu_reader}")
    add_executable(archive_texture_gpu_lifted "${texture_cpp}")
    target_link_libraries(archive_texture_gpu_lifted PRIVATE archive_codec_gpu_lifted ntdll)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_archive_texture_gpu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/archive_texture_gpu_check.py" "$<TARGET_FILE:pe_map>"
            "${archive_gpu_reader}" "$<TARGET_FILE:archive_texture_gpu_lifted>"
            "$<TARGET_FILE:archive_codec_gpu>" "$<TARGET_FILE:blast_source>")
        # 77: no physical adapter (hardware), or Control Flow Guard enforced for the pe_map runner (#1293).
        set_tests_properties(cpu_archive_texture_gpu_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77
            ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${adapter}")
    endforeach()

    add_library(archive_directory_gpu SHARED "${archive_src}/directory_gpu.cpp" "${archive_src}/quad_frames.cpp"
        "${CMAKE_CURRENT_BINARY_DIR}/tex_quad_vs.h" "${CMAKE_CURRENT_BINARY_DIR}/tex_quad_ps.h")
    target_include_directories(archive_directory_gpu PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
    target_compile_features(archive_directory_gpu PRIVATE cxx_std_17)
    target_link_libraries(archive_directory_gpu PRIVATE startup_stub_xcrdapi dxgi d3d12)
    set(directory_exe "${CMAKE_CURRENT_BINARY_DIR}/archive_directory_reader.exe")
    set(directory_cpp "${CMAKE_CURRENT_BINARY_DIR}/archive_directory_lifted.cpp")
    build_archive_reader("${archive_src}/directory_reader.zig" "${directory_exe}" "${directory_cpp}"
        archive_directory_gpu translate_directory.py EXPORT_SYMBOLS)
    add_executable(archive_directory_lifted "${directory_cpp}")
    target_link_libraries(archive_directory_lifted PRIVATE archive_directory_gpu ntdll)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_archive_directory_gpu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/archive_directory_gpu_check.py" "$<TARGET_FILE:pe_map>"
            "${directory_exe}" "$<TARGET_FILE:archive_directory_lifted>" "$<TARGET_FILE:archive_directory_gpu>")
        add_test(NAME cpu_archive_sixteen_page_gpu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/archive_directory_multipage_check.py" "$<TARGET_FILE:pe_map>"
            "${directory_exe}" "$<TARGET_FILE:archive_directory_lifted>" "$<TARGET_FILE:archive_directory_gpu>")
        set_tests_properties(cpu_archive_directory_gpu_${adapter} cpu_archive_sixteen_page_gpu_${adapter} PROPERTIES TIMEOUT 90
            ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${adapter}")
    endforeach()
    set_tests_properties(cpu_archive_directory_gpu_hardware cpu_archive_sixteen_page_gpu_hardware PROPERTIES SKIP_RETURN_CODE 77)

    function(crc_line_program target polynomial)
        # Use the same CRC object optimization flags in Debug and Release.
        set(crc_object "${CMAKE_CURRENT_BINARY_DIR}/${target}_step.obj")
        add_custom_command(OUTPUT "${crc_object}"
            COMMAND "${CMAKE_CXX_COMPILER}" /nologo /c /O1 /GS- /Zl "/DCRC_POLYNOMIAL=${polynomial}" "/Fo${crc_object}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/crc_line/crc_step.cpp"
            DEPENDS tests/cpu/crc_line/crc_step.cpp VERBATIM)
        add_executable(${target} tests/cpu/crc_line/entry.asm tests/cpu/exe_startup.asm "${crc_object}")
        set_target_properties(${target} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(${target} PRIVATE /ENTRY:native_startup /EXPORT:native_entry /EXPORT:crc_step
            /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
        target_link_libraries(${target} PRIVATE ucrt cpu_exe_io)
        set(crc_source "${CMAKE_CURRENT_BINARY_DIR}/${target}_lifted.cpp")
        add_custom_command(OUTPUT "${crc_source}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tools/cpu_stdio_exe_aot.py"
                "$<TARGET_FILE:${target}>" "${crc_source}" --entry-export native_entry
            DEPENDS ${target} tools/cpu_stdio_exe_aot.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
            VERBATIM)
        add_executable(${target}_lifted "${crc_source}")
        set_target_properties(${target}_lifted PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
    endfunction()
    crc_line_program(cpu_crc_line 0xedb88320u)
    crc_line_program(cpu_crc_castagnoli 0x82f63b78u)
    add_test(NAME cpu_native_crc_line COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/crc_line_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_crc_line>" "$<TARGET_FILE:cpu_crc_line_lifted>"
        "$<TARGET_FILE:cpu_crc_castagnoli>" "$<TARGET_FILE:cpu_crc_castagnoli_lifted>")
    # One-command conversion: tools/exe_aot.py translates and compiles each EXE at test time.
    add_test(NAME cpu_exe_aot_convert COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/exe_aot_check.py" "${CMAKE_CXX_COMPILER}"
        "$<TARGET_FILE:cpu_crc_line>" "$<TARGET_FILE:cpu_crc_castagnoli>" "$<TARGET_FILE:cpu_exe_original>"
        "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_exe_aot_convert PROPERTIES TIMEOUT 300)
    add_test(NAME cpu_exe_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu_exe_aot_cli_check.py")
    set_tests_properties(cpu_exe_aot_cli_check PROPERTIES TIMEOUT 60)
    add_library(cpu_exe_second_provider SHARED tests/cpu/exe_second_provider.cpp)
    target_link_libraries(cpu_exe_second_provider PRIVATE cpu_exe_io)
    foreach(variant IN ITEMS original inverted pair swapped framed image two_providers nested nested_bypass)
        set(native cpu_exe_${variant})
        set(lifted ${native}_lifted)
        add_executable(${native} tests/cpu/exe_entry.asm)
        if(variant STREQUAL "two_providers")
            target_sources(${native} PRIVATE tests/cpu/repeat_call.asm)
            target_compile_definitions(${native} PRIVATE TWO_PROVIDERS IMPORT_ACCUMULATE)
        else()
            target_sources(${native} PRIVATE tests/cpu/direct.asm)
        endif()
        set(entry_options)
        set(image_options)
        if(variant STREQUAL "image")
            target_compile_definitions(${native} PRIVATE IMAGE_SELECTOR)
            target_link_options(${native} PRIVATE /EXPORT:selector_result,DATA /EXPORT:selector_bias,DATA)
            list(APPEND image_options --image-data)
        endif()
        if(variant STREQUAL "framed" OR variant STREQUAL "image")
            target_sources(${native} PRIVATE tests/cpu/bare_calls.asm)
            target_compile_definitions(${native} PRIVATE FRAME_SELECTOR)
            target_link_options(${native} PRIVATE /EXPORT:call_bare "/MAP:${CMAKE_CURRENT_BINARY_DIR}/${native}.map")
            list(APPEND entry_options --frame-selector)
        endif()
        if(variant STREQUAL "pair" OR variant STREQUAL "swapped")
            target_sources(${native} PRIVATE tests/cpu/alt.asm)
            target_compile_definitions(${native} PRIVATE TWO_TARGETS)
        endif()
        if(variant STREQUAL "swapped")
            target_compile_definitions(${native} PRIVATE SWAP_TARGETS)
        endif()
        set_target_properties(${native} PROPERTIES LINKER_LANGUAGE CXX)
        target_compile_definitions(${native} PRIVATE IMPORT_MIX)
        if(variant MATCHES "^nested(_bypass)?$")
            target_sources(${native} PRIVATE tests/cpu/exe_nested.asm)
            target_compile_definitions(${native} PRIVATE NESTED_TARGET)
        endif()
        if(variant STREQUAL "nested_bypass")
            target_compile_definitions(${native} PRIVATE BYPASS_WRAPPER)
        endif()
        if(variant STREQUAL "inverted")
            target_compile_definitions(${native} PRIVATE FLIP_SELECTOR)
        endif()
        target_sources(${native} PRIVATE tests/cpu/exe_startup.asm)
        target_link_options(${native} PRIVATE /ENTRY:native_startup /EXPORT:native_entry /NODEFAULTLIB /INCREMENTAL:NO)
        set(extra_provider_args)
        set(extra_provider_target)
        if(variant STREQUAL "two_providers")
            set(extra_provider_args --provider "$<TARGET_FILE:cpu_exe_second_provider>" accumulate_args)
            set(extra_provider_target cpu_exe_second_provider)
        endif()
        set(source "${CMAKE_CURRENT_BINARY_DIR}/${lifted}.cpp")
        add_custom_command(OUTPUT "${source}"
            COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_exe_aot.py"
                "$<TARGET_FILE:${native}>" "$<TARGET_FILE:cpu_exe_io>"
                "$<TARGET_FILE:cpu_import_provider>" "${source}" --entry-export native_entry ${entry_options} ${extra_provider_args}
            DEPENDS ${native} cpu_exe_io cpu_import_provider ${extra_provider_target} tools/cpu_exe_aot.py
                tools/cpu_call_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py tools/ffx_version_query.py
            VERBATIM)
        add_executable(${lifted} "${source}")
        if(variant STREQUAL "image")
            set_source_files_properties("${source}" PROPERTIES COMPILE_DEFINITIONS "main=translated_entry")
            target_sources(${lifted} PRIVATE tests/cpu/exe_image_host.cpp)
            target_link_libraries(${lifted} PRIVATE pe_map)
        endif()
        if(variant STREQUAL "framed" OR variant STREQUAL "image")
            set(ranges "${CMAKE_CURRENT_BINARY_DIR}/${native}_ranges.json")
            set(selector "${CMAKE_CURRENT_BINARY_DIR}/${native}_selector.cpp")
            add_custom_command(OUTPUT "${selector}" BYPRODUCTS "${ranges}"
                COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/range_manifest.py"
                    "$<TARGET_FILE:${native}>" "${CMAKE_CURRENT_BINARY_DIR}/${native}.map" "${ranges}" bare_mix
                COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tools/cpu_switch_aot.py"
                    "$<TARGET_FILE:${native}>" call_bare "${selector}" --bind-ranges "${ranges}" ${image_options}
                DEPENDS ${native} tools/range_manifest.py tools/cpu_switch_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py
                VERBATIM)
            target_sources(${lifted} PRIVATE "${selector}")
        endif()
        target_link_options(${lifted} PRIVATE /INCREMENTAL:NO)
        foreach(program IN ITEMS ${native} ${lifted})
            target_link_libraries(${program} PRIVATE cpu_exe_io cpu_import_provider ${extra_provider_target})
        endforeach()
    endforeach()
    add_test(NAME cpu_aot_exe_entry COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/exe_entry_check.py"
        "$<TARGET_FILE:cpu_exe_original>" "$<TARGET_FILE:cpu_exe_original_lifted>"
        "$<TARGET_FILE:cpu_exe_inverted>" "$<TARGET_FILE:cpu_exe_inverted_lifted>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_import_provider>")
    add_test(NAME cpu_aot_exe_call_targets COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/exe_entry_check.py" --targets
        "$<TARGET_FILE:cpu_exe_pair>" "$<TARGET_FILE:cpu_exe_pair_lifted>"
        "$<TARGET_FILE:cpu_exe_swapped>" "$<TARGET_FILE:cpu_exe_swapped_lifted>")
    add_test(NAME cpu_aot_exe_nested_calls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/exe_entry_check.py" --nested
        "$<TARGET_FILE:cpu_exe_nested>" "$<TARGET_FILE:cpu_exe_nested_lifted>"
        "$<TARGET_FILE:cpu_exe_nested_bypass>" "$<TARGET_FILE:cpu_exe_nested_bypass_lifted>")
    add_test(NAME cpu_aot_ordinal_import COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/import_check.py" "$<TARGET_FILE:cpu_ordinal_original>"
        "$<TARGET_FILE:cpu_ordinal_original_lifted>" "$<TARGET_FILE:cpu_ordinal_provider>"
        "$<TARGET_FILE:cpu_ordinal_altered>" "$<TARGET_FILE:cpu_register_probe>"
        --ordinal-control "$<TARGET_FILE:cpu_import_provider>")
    cpu_asm_fixture(cpu_reloc_original reloc_route)
    target_link_libraries(cpu_reloc_original PRIVATE cpu_import_provider)
    add_test(NAME cpu_native_highlow COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/highlow_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_reloc_original>" "$<TARGET_FILE:cpu_import_provider>")
    cpu_asm_fixture(cpu_two_imports two_imports)
    target_link_libraries(cpu_two_imports PRIVATE cpu_import_provider cpu_register_probe)
    add_library(pe_map SHARED tools/pe_map.cpp)
    target_link_libraries(pe_map PRIVATE bcrypt)
    add_library(cpu_shim_startup_guest SHARED tests/cpu/shim_startup.cpp)
    target_compile_features(cpu_shim_startup_guest PRIVATE cxx_std_17)
    set_target_properties(cpu_shim_startup_guest PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreaded)
    target_link_libraries(cpu_shim_startup_guest PRIVATE xmem_shim d3d12_xs_shim)
    add_library(cpu_shim_compute SHARED tests/cpu/shim_compute_provider.cpp tests/cpu/shim_compute_gpu.cpp)
    add_dependencies(cpu_shim_compute pso_compute_headers)
    target_include_directories(cpu_shim_compute PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
    target_compile_features(cpu_shim_compute PRIVATE cxx_std_17)
    target_link_libraries(cpu_shim_compute PRIVATE xmem_shim dxgi d3d12)
    set(tex_tables "${CMAKE_CURRENT_BINARY_DIR}/tex_tables.h")
    add_custom_command(OUTPUT "${tex_tables}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/tex_gen.py" "${tex_tables}"
        DEPENDS tests/cpu/tex_gen.py tests/bc7_draw_check.py tools/bc7_blocks.py tools/bc7_tiles.py VERBATIM)
    add_library(cpu_shim_draw SHARED tests/cpu/shim_draw_provider.cpp tests/cpu/shim_draw_gpu.cpp
        tests/cpu/shim_chain_gpu.cpp tests/cpu/shim_tex_gpu.cpp tests/desktop_gpu.cpp
        tests/mesh_shadow_draw.cpp)
    set(shim_draw_color_header "${CMAKE_CURRENT_BINARY_DIR}/shim_draw_color.h")
    add_custom_command(OUTPUT "${shim_draw_color_header}"
        COMMAND "${DXC_EXECUTABLE}" -T ps_6_0 -E main -Fh "${shim_draw_color_header}" -Vn shim_draw_color
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_draw_color.hlsl"
        DEPENDS tests/cpu/shim_draw_color.hlsl VERBATIM)
    foreach(stage IN ITEMS texture_init texture_read texture_swap)
        set(profile ps_6_0)
        set(definition)
        if(stage STREQUAL texture_init)
            set(profile cs_6_0)
            set(definition -DINITIALIZE_TEXTURE)
        elseif(stage STREQUAL texture_swap)
            set(definition -DSWAP_CHANNELS)
        endif()
        set(header "${CMAKE_CURRENT_BINARY_DIR}/shim_draw_${stage}.h")
        add_custom_command(OUTPUT "${header}"
            COMMAND "${DXC_EXECUTABLE}" -T "${profile}" -E main ${definition}
                -Fh "${header}" -Vn "shim_draw_${stage}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_draw_texture.hlsl"
            DEPENDS tests/cpu/shim_draw_texture.hlsl VERBATIM)
        target_sources(cpu_shim_draw PRIVATE "${header}")
    endforeach()
    add_dependencies(cpu_shim_draw triangle_headers)
    target_sources(cpu_shim_draw PRIVATE
        "${shim_draw_color_header}"
        "${CMAKE_CURRENT_BINARY_DIR}/triangle_vs.h"
        "${CMAKE_CURRENT_BINARY_DIR}/triangle_ps.h"
        "${CMAKE_CURRENT_BINARY_DIR}/triangle_vs_flip.h"
        "${CMAKE_CURRENT_BINARY_DIR}/triangle_ps_flip.h"
        "${CMAKE_CURRENT_BINARY_DIR}/tex_quad_vs.h"
        "${CMAKE_CURRENT_BINARY_DIR}/tex_quad_ps.h"
        "${tex_tables}")
    target_include_directories(cpu_shim_draw PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
    target_compile_features(cpu_shim_draw PRIVATE cxx_std_17)
    target_link_libraries(cpu_shim_draw PRIVATE dxgi d3d12)
    add_executable(cpu_shim_startup tests/cpu/shim_startup.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_shim_startup PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_shim_startup PRIVATE /ENTRY:native_startup /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_shim_startup PRIVATE cpu_shim_startup_guest cpu_exe_io cpu_shim_compute cpu_shim_draw d3d12_xs_shim)
    set(shim_startup_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_shim_startup_lifted.cpp")
    add_custom_command(OUTPUT "${shim_startup_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/translate_shim_startup.py"
            "$<TARGET_FILE:cpu_shim_startup>" "${shim_startup_cpp}"
        DEPENDS cpu_shim_startup tests/cpu/translate_shim_startup.py tools/cpu_switch_aot.py
            tools/cpu_call_aot.py tools/cpu_leaf_aot.py tools/cpu_ranges.py VERBATIM)
    add_library(cpu_placed_dxr_provider SHARED tests/cpu/placed_dxr_provider.cpp tests/dxr_check.cpp
        tests/desktop_gpu.cpp src/era_title_va.cpp
        "${ray_header}" "${ray_table_header}" "${ray_pipeline_header}" "${candidates_header}" "${candidates_pipeline_header}")
    if(TARGET d3d12_xs_device_obj)
        target_sources(cpu_placed_dxr_provider PRIVATE $<TARGET_OBJECTS:d3d12_xs_device_obj>)
    else()
        target_sources(cpu_placed_dxr_provider PRIVATE src/startup_stubs/d3d12_xs_device.cpp)
    endif()
    target_include_directories(cpu_placed_dxr_provider PRIVATE tests src "${CMAKE_CURRENT_BINARY_DIR}")
    target_link_libraries(cpu_placed_dxr_provider PRIVATE d3d12 dxgi dxguid d3dcompiler user32 gdi32 x2w_build_rev)
    target_compile_features(cpu_placed_dxr_provider PRIVATE cxx_std_17)
    add_executable(cpu_placed_dxr tests/cpu/placed_dxr.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_placed_dxr PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_placed_dxr PRIVATE /ENTRY:native_startup /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_placed_dxr PRIVATE cpu_placed_dxr_provider cpu_exe_io)
    set(placed_dxr_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_placed_dxr_lifted.cpp")
    add_custom_command(OUTPUT "${placed_dxr_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/translate_placed_dxr.py"
            "$<TARGET_FILE:cpu_placed_dxr>" "${placed_dxr_cpp}"
        DEPENDS cpu_placed_dxr tests/cpu/translate_placed_dxr.py tests/cpu/translate_shim_startup.py tools/cpu_switch_aot.py)
    add_executable(cpu_placed_dxr_lifted "${placed_dxr_cpp}")
    target_compile_features(cpu_placed_dxr_lifted PRIVATE cxx_std_17)
    target_link_libraries(cpu_placed_dxr_lifted PRIVATE cpu_placed_dxr_provider cpu_exe_io)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_placed_dxr_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/placed_dxr_check.py" ${adapter} "$<TARGET_FILE:pe_map>"
            "$<TARGET_FILE:cpu_placed_dxr>" "$<TARGET_FILE:cpu_placed_dxr_lifted>"
            "$<TARGET_FILE:cpu_placed_dxr_provider>" "$<TARGET_FILE:cpu_exe_io>")
        set_tests_properties(cpu_placed_dxr_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    add_library(cpu_placed_provider SHARED tests/cpu/placed_draw_provider.cpp tests/startup_stream_setup.cpp)
    target_compile_features(cpu_placed_provider PRIVATE cxx_std_17)
    target_link_libraries(cpu_placed_provider PRIVATE d3d12_xs_shim d3d12 dxgi)
    add_executable(cpu_placed_draw tests/cpu/placed_draw.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_placed_draw PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_placed_draw PRIVATE /ENTRY:native_startup /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_placed_draw PRIVATE cpu_placed_provider cpu_exe_io)
    set(placed_cpp "${CMAKE_CURRENT_BINARY_DIR}/cpu_placed_draw_lifted.cpp")
    add_custom_command(OUTPUT "${placed_cpp}"
        COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/translate_placed_draw.py"
            "$<TARGET_FILE:cpu_placed_draw>" "${placed_cpp}"
        DEPENDS cpu_placed_draw tests/cpu/translate_placed_draw.py tests/cpu/translate_shim_startup.py tools/cpu_switch_aot.py)
    add_executable(cpu_placed_draw_lifted "${placed_cpp}")
    target_compile_features(cpu_placed_draw_lifted PRIVATE cxx_std_17)
    target_link_libraries(cpu_placed_draw_lifted PRIVATE cpu_placed_provider cpu_exe_io)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_placed_draw_${adapter} COMMAND "${CMAKE_COMMAND}" -E env "X2W_FXC=${STARTUP_FXC}"
            "${INTAKE_PYTHON}" -B "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/placed_draw_check.py" "${adapter}"
            "$<TARGET_FILE:startup_stream_consumer>" "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_placed_draw>"
            "$<TARGET_FILE:cpu_placed_draw_lifted>" "$<TARGET_FILE:cpu_placed_provider>" "$<TARGET_FILE:cpu_exe_io>")
        set_tests_properties(cpu_placed_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
    endforeach()
    add_executable(cpu_shim_startup_lifted "${shim_startup_cpp}")
    target_compile_features(cpu_shim_startup_lifted PRIVATE cxx_std_17)
    target_link_libraries(cpu_shim_startup_lifted PRIVATE cpu_shim_startup_guest cpu_exe_io cpu_shim_compute cpu_shim_draw d3d12_xs_shim)
    add_test(NAME cpu_native_shim_startup COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/shim_startup_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_shim_startup>" "$<TARGET_FILE:cpu_shim_startup_guest>" "$<TARGET_FILE:cpu_exe_io>"
        "$<TARGET_FILE:xmem_shim>" "$<TARGET_FILE:d3d12_xs_shim>")
    set_tests_properties(cpu_native_shim_startup PROPERTIES TIMEOUT 100
        ENVIRONMENT "X2W_SHIM_COMPUTE_CASE=;X2W_SHIM_DRAW_CASE=")
    # Recording stand-ins for the main executable's D3D12ConfigureVirtualMemoryX call (#874).
    # They keep the d3d12_xs.dll and xmem.dll names in their own directory, next to the fixture EXEs.
    set(configure_vm_dir "${CMAKE_CURRENT_BINARY_DIR}/configure_vm")
    foreach(provider IN ITEMS d3d12_xs xmem)
        add_library(cpu_configure_vm_${provider} SHARED tests/cpu/configure_vm_recorder.cpp
            tests/cpu/configure_vm_${provider}.def)
        set_target_properties(cpu_configure_vm_${provider} PROPERTIES OUTPUT_NAME ${provider}
            MSVC_RUNTIME_LIBRARY MultiThreaded
            RUNTIME_OUTPUT_DIRECTORY "${configure_vm_dir}" ARCHIVE_OUTPUT_DIRECTORY "${configure_vm_dir}")
    endforeach()
    set(configure_vm_io "${configure_vm_dir}/cpu_exe_io.dll")
    add_custom_command(OUTPUT "${configure_vm_io}"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${configure_vm_dir}"
        COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:cpu_exe_io>" "${configure_vm_io}"
        DEPENDS cpu_exe_io VERBATIM)
    add_custom_target(cpu_configure_vm_io DEPENDS "${configure_vm_io}")
    foreach(sample IN ITEMS 3 4)
        add_executable(cpu_configure_vm_${sample} tests/cpu/configure_vm.asm tests/cpu/exe_startup.asm)
        add_dependencies(cpu_configure_vm_${sample} cpu_configure_vm_io)
        target_compile_definitions(cpu_configure_vm_${sample} PRIVATE SAMPLE=${sample})
        set_target_properties(cpu_configure_vm_${sample} PROPERTIES LINKER_LANGUAGE CXX
            RUNTIME_OUTPUT_DIRECTORY "${configure_vm_dir}")
        target_link_options(cpu_configure_vm_${sample} PRIVATE
            /ENTRY:native_startup /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
        target_link_libraries(cpu_configure_vm_${sample} PRIVATE cpu_configure_vm_d3d12_xs cpu_configure_vm_xmem cpu_exe_io)
    endforeach()
    add_test(NAME cpu_native_configure_vm COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/configure_vm_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_configure_vm_3>" "$<TARGET_FILE:cpu_configure_vm_4>")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_shim_compute_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_compute_check.py"
            "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_shim_startup>" "$<TARGET_FILE:cpu_shim_startup_lifted>"
            "$<TARGET_FILE:cpu_shim_startup_guest>" "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:xmem_shim>"
            "$<TARGET_FILE:d3d12_xs_shim>")
        set_tests_properties(cpu_shim_compute_${adapter} PROPERTIES TIMEOUT 120
            ENVIRONMENT "X2W_SHIM_COMPUTE_ADAPTER=${adapter};X2W_SHIM_DRAW_CASE=")
    endforeach()
    set_tests_properties(cpu_shim_compute_hardware PROPERTIES SKIP_RETURN_CODE 77)
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_shim_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_draw_check.py"
            "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_shim_startup>" "$<TARGET_FILE:cpu_shim_startup_lifted>"
            "$<TARGET_FILE:cpu_shim_startup_guest>" "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:xmem_shim>"
            "$<TARGET_FILE:d3d12_xs_shim>" "$<TARGET_FILE:cpu_shim_draw>")
        set_tests_properties(cpu_shim_draw_${adapter} PROPERTIES TIMEOUT 180
            ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${adapter};X2W_SHIM_COMPUTE_CASE=")
        add_test(NAME cpu_shim_texture_reuse_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_draw_check.py"
            "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_shim_startup>" "$<TARGET_FILE:cpu_shim_startup_lifted>"
            "$<TARGET_FILE:cpu_shim_startup_guest>" "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:xmem_shim>"
            "$<TARGET_FILE:d3d12_xs_shim>" "$<TARGET_FILE:cpu_shim_draw>" --texture-reuse)
        set_tests_properties(cpu_shim_texture_reuse_${adapter} PROPERTIES TIMEOUT 180
            ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${adapter};X2W_SHIM_COMPUTE_CASE=")
    endforeach()
    set_tests_properties(cpu_shim_draw_hardware cpu_shim_texture_reuse_hardware PROPERTIES SKIP_RETURN_CODE 77)
    # Uploaded RGBA8 and BC7 textures sampled through a vertex-buffer quad from the same EXE entry.
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_shim_upload_texture_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_tex_check.py"
            "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_shim_startup>" "$<TARGET_FILE:cpu_shim_startup_lifted>"
            "$<TARGET_FILE:cpu_shim_startup_guest>" "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:xmem_shim>"
            "$<TARGET_FILE:d3d12_xs_shim>" "$<TARGET_FILE:cpu_shim_draw>")
        set_tests_properties(cpu_shim_upload_texture_${adapter} PROPERTIES TIMEOUT 180
            ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${adapter};X2W_SHIM_COMPUTE_CASE=")
    endforeach()
    set_tests_properties(cpu_shim_upload_texture_hardware PROPERTIES SKIP_RETURN_CODE 77)
    # The translated compute -> mesh -> pixel chain (#658) from the same EXE entry (#671).
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME cpu_shim_chain_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_chain_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_shim_startup>" "$<TARGET_FILE:cpu_shim_startup_lifted>"
            "$<TARGET_FILE:cpu_shim_startup_guest>" "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:xmem_shim>"
            "$<TARGET_FILE:d3d12_xs_shim>" "$<TARGET_FILE:cpu_shim_draw>")
        set_tests_properties(cpu_shim_chain_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77
            ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${adapter};X2W_SHIM_COMPUTE_CASE=")
        add_test(NAME cpu_shim_shadow_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpu/shim_shadow_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_shim_startup>" "$<TARGET_FILE:cpu_shim_startup_lifted>"
            "$<TARGET_FILE:cpu_shim_startup_guest>" "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:xmem_shim>"
            "$<TARGET_FILE:d3d12_xs_shim>" "$<TARGET_FILE:cpu_shim_draw>")
        set_tests_properties(cpu_shim_shadow_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77
            ENVIRONMENT "X2W_SHIM_DRAW_ADAPTER=${adapter};X2W_SHIM_COMPUTE_CASE=")
    endforeach()

    add_test(NAME cpu_native_exe_chain COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/mapped_exe_chain_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_original>" "$<TARGET_FILE:cpu_exe_original_lifted>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_import_provider>")
    add_test(NAME cpu_native_exe_frame_chain COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/mapped_exe_chain_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_framed>" "$<TARGET_FILE:cpu_exe_framed_lifted>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_import_provider>" "$<TARGET_FILE:cpu_exe_original>")
    add_test(NAME cpu_native_exe_image_chain COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/exe_image_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_image>" "$<TARGET_FILE:cpu_exe_image_lifted>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_import_provider>")
    add_test(NAME cpu_native_exe_two_providers COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/mapped_exe_chain_check.py" --two-providers "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_two_providers>" "$<TARGET_FILE:cpu_exe_two_providers_lifted>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_import_provider>" "$<TARGET_FILE:cpu_exe_second_provider>")
    target_compile_features(pe_map PRIVATE cxx_std_17)
    add_test(NAME cpu_native_exe_termination COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/exe_termination_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_original>" "$<TARGET_FILE:cpu_exe_original_lifted>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_import_provider>")
    add_test(NAME cpu_native_map COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_map_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_register_probe>"
        --named "$<TARGET_FILE:cpu_import_original>" "$<TARGET_FILE:cpu_import_original_lifted>"
            "$<TARGET_FILE:cpu_import_provider>" "$<TARGET_FILE:cpu_import_altered>"
        --ordinal "$<TARGET_FILE:cpu_ordinal_original>" "$<TARGET_FILE:cpu_ordinal_original_lifted>"
            "$<TARGET_FILE:cpu_ordinal_provider>" "$<TARGET_FILE:cpu_ordinal_altered>"
        --reloc "$<TARGET_FILE:cpu_reloc_original>" "$<TARGET_FILE:cpu_import_provider>"
            "$<TARGET_FILE:cpu_import_altered>"
        --two "$<TARGET_FILE:cpu_two_imports>" "$<TARGET_FILE:cpu_import_provider>"
            "$<TARGET_FILE:cpu_register_probe>")
    add_test(NAME cpu_native_mutation COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_mutation_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_register_probe>" "$<TARGET_FILE:cpu_import_original>"
        --provider "$<TARGET_FILE:cpu_import_provider>")
    add_test(NAME cpu_native_reloc_free COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_reloc_free_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_register_probe>" "$<TARGET_FILE:cpu_import_original>"
        "$<TARGET_FILE:cpu_import_provider>")
    cpu_asm_fixture(cpu_forwarder forwarder)
    target_link_libraries(cpu_forwarder PRIVATE cpu_import_provider)
    add_test(NAME cpu_native_forwarder COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/forwarder_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_forwarder>" "$<TARGET_FILE:cpu_import_provider>")
    cpu_asm_fixture(cpu_seh_original seh_route)
    add_test(NAME cpu_native_seh COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_seh_check.py" "$<TARGET_FILE:cpu_seh_original>"
        "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_register_probe>")
    add_test(NAME cpu_native_section COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_section_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_register_probe>")
    # A load that never returns ends the test; its last "start" line names the case.
    set_tests_properties(cpu_native_section PROPERTIES TIMEOUT 120)
    add_library(cpu_tls_sink SHARED tests/cpu/tls_sink.cpp)
    foreach(variant IN ITEMS original refuse)
        add_library(cpu_tls_${variant} SHARED tests/cpu/tls_route.asm tests/cpu/tls_route.def)
        set_target_properties(cpu_tls_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(cpu_tls_${variant} PRIVATE /ENTRY:dll_entry /NODEFAULTLIB /INCREMENTAL:NO)
        target_link_libraries(cpu_tls_${variant} PRIVATE cpu_tls_sink)
    endforeach()
    target_compile_definitions(cpu_tls_refuse PRIVATE ENTRY_FAILS)
    add_test(NAME cpu_native_tls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_tls_check.py" "$<TARGET_FILE:cpu_tls_original>"
        "$<TARGET_FILE:cpu_tls_refuse>" "$<TARGET_FILE:cpu_tls_sink>" "$<TARGET_FILE:pe_map>")
    # Implicit TLS data: initialized, zero-filled, aligned, relocated and dynamically initialized
    # thread-locals seen from the loading thread, an existing thread and a new thread.
    foreach(variant IN ITEMS cpu_tls_data cpu_tls_data_refuse)
        add_library(${variant} SHARED tests/cpu/tls_data.cpp)
        set_target_properties(${variant} PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreaded)
        target_link_options(${variant} PRIVATE /INCREMENTAL:NO)
    endforeach()
    target_compile_definitions(cpu_tls_data_refuse PRIVATE ENTRY_FAILS)
    add_test(NAME cpu_native_tls_data COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_tls_data_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_tls_data>" "$<TARGET_FILE:cpu_tls_data_refuse>")
    # Implicit-TLS differential: one __declspec(thread) value read in the TLS callback
    # on the main and worker threads, under the Windows loader and under pe_map.
    add_library(cpu_tls_value SHARED tests/cpu/tls_value.cpp)
    set_target_properties(cpu_tls_value PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreaded)
    target_link_options(cpu_tls_value PRIVATE /INCREMENTAL:NO)
    target_link_libraries(cpu_tls_value PRIVATE cpu_tls_sink)
    add_test(NAME cpu_native_tls_value COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_tls_value_check.py" "$<TARGET_FILE:cpu_tls_value>"
        "$<TARGET_FILE:cpu_tls_original>" "$<TARGET_FILE:cpu_tls_sink>" "$<TARGET_FILE:pe_map>")
    # Provider variant that starts a ready worker inside mix_args; the control installs it as cpu_import_provider.dll.
    add_library(cpu_import_live SHARED tests/cpu/import_provider.cpp tests/cpu/named_provider.def)
    target_compile_definitions(cpu_import_live PRIVATE LIVE_WORKER)
    target_link_libraries(cpu_import_live PRIVATE cpu_exe_io)
    # Simulation control: finish_exe never terminates; the control installs it as cpu_exe_io.dll.
    add_library(cpu_exe_io_hang SHARED tests/cpu/exe_io.cpp)
    target_compile_definitions(cpu_exe_io_hang PRIVATE FINISH_HANG)
    add_library(cpu_cookie_dll SHARED tests/cpu/load_cookie.asm)
    add_executable(cpu_cookie_exe tests/cpu/load_cookie.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_cookie_dll cpu_cookie_exe PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_cookie_dll PRIVATE /ENTRY:fixture_entry /EXPORT:read_cookie
        /NODEFAULTLIB /SUBSYSTEM:WINDOWS,6.00 /DYNAMICBASE /INCREMENTAL:NO)
    target_link_options(cpu_cookie_exe PRIVATE /ENTRY:native_startup
        /NODEFAULTLIB /SUBSYSTEM:CONSOLE,6.00 /DYNAMICBASE /INCREMENTAL:NO)
    target_link_libraries(cpu_cookie_exe PRIVATE cpu_exe_io)
    add_test(NAME cpu_native_load_cookie COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/load_cookie_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_cookie_dll>" "$<TARGET_FILE:cpu_cookie_exe>" "$<TARGET_FILE:cpu_exe_io>")
    add_test(NAME cpu_package_shim_lifetime COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/package_shim_lifetime_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_cookie_exe>" "$<TARGET_FILE:cpu_exe_io>")
    foreach(variant IN ITEMS present absent alternate)
        add_executable(cpu_load_dispatch_${variant} tests/cpu/load_config_dispatch.asm tests/cpu/exe_startup.asm)
        set_target_properties(cpu_load_dispatch_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(cpu_load_dispatch_${variant} PRIVATE
            /ENTRY:native_startup /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_load_dispatch_${variant} PRIVATE cpu_exe_io)
        if(variant STREQUAL absent)
            target_compile_options(cpu_load_dispatch_${variant} PRIVATE /DDISPATCH_ABSENT)
        elseif(variant STREQUAL alternate)
            target_compile_options(cpu_load_dispatch_${variant} PRIVATE /DDISPATCH_ALTERNATE)
        endif()
    endforeach()
    add_test(NAME cpu_native_load_dispatch COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/load_config_dispatch_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_load_dispatch_present>" "$<TARGET_FILE:cpu_load_dispatch_absent>"
        "$<TARGET_FILE:cpu_load_dispatch_alternate>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_load_dispatch PROPERTIES TIMEOUT 30)
    # A typed callback called through the linker-produced load-config dispatch slot (#903). The same
    # objects are linked without and with /guard:cf. OTHER is the negative control; INVALID calls a
    # target inside a function. Based on denn0x's pe/load-config-callback reference branch.
    foreach(variant IN ITEMS record other invalid cfg_record cfg_invalid)
        add_executable(cpu_load_callback_${variant} tests/cpu/load_config_callback.asm
            tests/cpu/load_config_callback.cpp tests/cpu/exe_startup.asm)
        set_target_properties(cpu_load_callback_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_compile_options(cpu_load_callback_${variant} PRIVATE
            $<$<COMPILE_LANGUAGE:CXX>:/guard:cf /GS- /Zl>)
        target_link_options(cpu_load_callback_${variant} PRIVATE /ENTRY:native_startup
            /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_load_callback_${variant} PRIVATE cpu_exe_io)
        if(variant MATCHES "^cfg_")
            target_link_options(cpu_load_callback_${variant} PRIVATE /guard:cf)
        endif()
        if(variant MATCHES "other")
            target_compile_definitions(cpu_load_callback_${variant} PRIVATE OTHER)
        elseif(variant MATCHES "invalid")
            target_compile_definitions(cpu_load_callback_${variant} PRIVATE INVALID)
        endif()
    endforeach()
    add_test(NAME cpu_native_load_config_callback COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/load_config_callback_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_load_callback_record>"
        "$<TARGET_FILE:cpu_load_callback_other>" "$<TARGET_FILE:cpu_load_callback_invalid>"
        "$<TARGET_FILE:cpu_load_callback_cfg_record>" "$<TARGET_FILE:cpu_load_callback_cfg_invalid>")
    set_tests_properties(cpu_native_load_config_callback PROPERTIES TIMEOUT 120)
    foreach(variant IN ITEMS original no_tls)
        add_executable(cpu_exe_start_${variant} tests/cpu/exe_start.asm tests/cpu/exe_startup.asm)
        set_target_properties(cpu_exe_start_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(cpu_exe_start_${variant} PRIVATE /ENTRY:native_startup /EXPORT:native_entry
            /EXPORT:body_status,DATA /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_exe_start_${variant} PRIVATE cpu_import_provider cpu_exe_io)
    endforeach()
    target_compile_definitions(cpu_exe_start_no_tls PRIVATE NO_TLS)
    add_test(NAME cpu_native_exe_start COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_exe_start_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_start_original>" "$<TARGET_FILE:cpu_exe_start_no_tls>"
        "$<TARGET_FILE:cpu_import_provider>" "$<TARGET_FILE:cpu_import_altered>"
        "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_import_live>" "$<TARGET_FILE:cpu_exe_io_hang>")
    # An EXE that imports XMemAllocatePhysicalPages and XMemFreePhysicalPages by name (#880), started by
    # Windows and by pe_map. FULL_COUNT and SKIP_RELEASE are negative controls.
    foreach(variant IN ITEMS original full_count skip_release)
        add_executable(cpu_xmem_physical_${variant} tests/cpu/xmem_physical_pair.asm tests/cpu/exe_startup.asm)
        set_target_properties(cpu_xmem_physical_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(cpu_xmem_physical_${variant} PRIVATE /ENTRY:native_startup
            /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_xmem_physical_${variant} PRIVATE xmem_shim cpu_exe_io)
    endforeach()
    target_compile_definitions(cpu_xmem_physical_full_count PRIVATE FULL_COUNT)
    target_compile_definitions(cpu_xmem_physical_skip_release PRIVATE SKIP_RELEASE)
    add_test(NAME cpu_native_xmem_physical_pair COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/xmem_physical_pair_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_xmem_physical_original>" "$<TARGET_FILE:cpu_xmem_physical_full_count>"
        "$<TARGET_FILE:cpu_xmem_physical_skip_release>" "$<TARGET_FILE:xmem_shim>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_xmem_physical_pair PROPERTIES TIMEOUT 120)
    # An EXE that imports XMemVirtualAlloc by name and uses the four reserve+commit startup call shapes
    # (#870), started by Windows and by pe_map. The six variants after original are negative controls.
    foreach(variant IN ITEMS original reserve_only misaligned dirty accepted_refusal host_fit skip_release)
        add_executable(cpu_xmem_pool_${variant} tests/cpu/xmem_pool_commit.asm tests/cpu/exe_startup.asm)
        set_target_properties(cpu_xmem_pool_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(cpu_xmem_pool_${variant} PRIVATE /ENTRY:native_startup
            /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_xmem_pool_${variant} PRIVATE xmem_shim cpu_exe_io kernel32)
    endforeach()
    target_compile_definitions(cpu_xmem_pool_reserve_only PRIVATE RESERVE_ONLY)
    target_compile_definitions(cpu_xmem_pool_misaligned PRIVATE MISALIGNED)
    target_compile_definitions(cpu_xmem_pool_dirty PRIVATE DIRTY)
    target_compile_definitions(cpu_xmem_pool_accepted_refusal PRIVATE ACCEPTED_REFUSAL)
    target_compile_definitions(cpu_xmem_pool_host_fit PRIVATE HOST_FIT)
    target_compile_definitions(cpu_xmem_pool_skip_release PRIVATE SKIP_RELEASE)
    add_test(NAME cpu_native_xmem_pool_commit COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/xmem_pool_commit_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_xmem_pool_original>" "$<TARGET_FILE:cpu_xmem_pool_reserve_only>"
        "$<TARGET_FILE:cpu_xmem_pool_misaligned>"
        "$<TARGET_FILE:cpu_xmem_pool_dirty>" "$<TARGET_FILE:cpu_xmem_pool_accepted_refusal>"
        "$<TARGET_FILE:cpu_xmem_pool_host_fit>" "$<TARGET_FILE:cpu_xmem_pool_skip_release>"
        "$<TARGET_FILE:xmem_shim>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_xmem_pool_commit PROPERTIES TIMEOUT 120)
    # An EXE that imports XMemAllocDefault and XMemFreeDefault by name (#875, exports from #879), started
    # by Windows and by pe_map. SKIP_GPU_FREE, SKIP_HEAP_FREE and UNINDUCED are negative controls.
    add_library(cpu_heap_probe SHARED tests/cpu/heap_probe.cpp)
    foreach(variant IN ITEMS original skip_gpu_free skip_heap_free uninduced)
        add_executable(cpu_xmem_default_${variant} tests/cpu/xmem_default_pair.asm tests/cpu/exe_startup.asm)
        set_target_properties(cpu_xmem_default_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(cpu_xmem_default_${variant} PRIVATE /ENTRY:native_startup
            /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_xmem_default_${variant} PRIVATE xmem_shim cpu_exe_io cpu_heap_probe kernel32)
    endforeach()
    target_compile_definitions(cpu_xmem_default_skip_gpu_free PRIVATE SKIP_GPU_FREE)
    target_compile_definitions(cpu_xmem_default_skip_heap_free PRIVATE SKIP_HEAP_FREE)
    target_compile_definitions(cpu_xmem_default_uninduced PRIVATE UNINDUCED)
    add_test(NAME cpu_native_xmem_default_pair COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/xmem_default_pair_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_xmem_default_original>" "$<TARGET_FILE:cpu_xmem_default_skip_gpu_free>"
        "$<TARGET_FILE:cpu_xmem_default_skip_heap_free>" "$<TARGET_FILE:cpu_xmem_default_uninduced>"
        "$<TARGET_FILE:xmem_shim>" "$<TARGET_FILE:cpu_exe_io>" "$<TARGET_FILE:cpu_heap_probe>")
    set_tests_properties(cpu_native_xmem_default_pair PROPERTIES TIMEOUT 180)

    foreach(variant IN ITEMS original returning no_worker)
        add_executable(cpu_exe_worker_alive_${variant} tests/cpu/worker_alive_entry.asm)
        set_target_properties(cpu_exe_worker_alive_${variant} PROPERTIES LINKER_LANGUAGE CXX)
        target_link_options(cpu_exe_worker_alive_${variant} PRIVATE /ENTRY:worker_alive_entry
            /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_exe_worker_alive_${variant} PRIVATE kernel32)
    endforeach()
    # The worker decides whether a process outlives its entry thread; the return path stays the
    # variable so the fixtures can be compared without touching the shared entry.
    target_compile_definitions(cpu_exe_worker_alive_returning PRIVATE RETURN_FROM_ENTRY)
    target_compile_definitions(cpu_exe_worker_alive_no_worker PRIVATE RETURN_FROM_ENTRY NO_WORKER)
    add_test(NAME cpu_native_worker_alive COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/hang_probe.py" --control --launches 2 --timeout 2
        --eof-timeout 0.5
        "$<TARGET_FILE:cpu_exe_worker_alive_original>"
        "$<TARGET_FILE:cpu_exe_worker_alive_returning>"
        "$<TARGET_FILE:cpu_exe_worker_alive_no_worker>")
    # The probe waits at most 2 s for a launch and 0.5 s for end of input, so it must not share the
    # machine with other tests when CTest runs tests in parallel.
    set_tests_properties(cpu_native_worker_alive PROPERTIES RUN_SERIAL TRUE)
    # Two CRT-free DLLs and an EXE: A has no imports, B imports A, the EXE imports both.
    foreach(dll IN ITEMS a a_alt b b_noinit)
        string(REGEX REPLACE "_(noinit|alt)$" "" source "${dll}")
        add_library(cpu_startup_${dll} SHARED tests/cpu/startup_${source}.cpp)
        target_compile_options(cpu_startup_${dll} PRIVATE /GS- /Zl)
        target_link_options(cpu_startup_${dll} PRIVATE /ENTRY:${source}_main /NODEFAULTLIB /INCREMENTAL:NO)
        target_link_libraries(cpu_startup_${dll} PRIVATE kernel32)
    endforeach()
    target_compile_definitions(cpu_startup_b_noinit PRIVATE NO_INIT)
    target_compile_definitions(cpu_startup_a_alt PRIVATE ALTER)
    target_link_libraries(cpu_startup_b PRIVATE cpu_startup_a)
    target_link_libraries(cpu_startup_b_noinit PRIVATE cpu_startup_a)
    add_executable(cpu_startup_exe tests/cpu/startup_exe.cpp)
    target_compile_options(cpu_startup_exe PRIVATE /GS- /Zl)
    target_link_options(cpu_startup_exe PRIVATE /ENTRY:exe_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE
        /INCREMENTAL:NO)
    target_link_libraries(cpu_startup_exe PRIVATE kernel32 cpu_startup_a cpu_startup_b)
    foreach(control IN ITEMS timeout create)  # controls: a worker that outlives the wait, and one that cannot start
        add_executable(cpu_startup_exe_${control} tests/cpu/startup_exe.cpp)
        string(TOUPPER "${control}" definition)
        target_compile_definitions(cpu_startup_exe_${control} PRIVATE ${definition}_CONTROL)
        target_compile_options(cpu_startup_exe_${control} PRIVATE /GS- /Zl)
        target_link_options(cpu_startup_exe_${control} PRIVATE /ENTRY:exe_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE
            /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_startup_exe_${control} PRIVATE kernel32 cpu_startup_a cpu_startup_b)
    endforeach()
    # Lingering-thread controls (#1375): a thread outlives the entry point; _linger_return ends as before.
    foreach(control IN ITEMS linger linger_return)
        add_executable(cpu_startup_exe_${control} tests/cpu/startup_exe.cpp)
        target_compile_definitions(cpu_startup_exe_${control} PRIVATE LINGER_CONTROL)
        target_compile_options(cpu_startup_exe_${control} PRIVATE /GS- /Zl)
        target_link_options(cpu_startup_exe_${control} PRIVATE /ENTRY:exe_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE
            /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(cpu_startup_exe_${control} PRIVATE kernel32 cpu_startup_a cpu_startup_b)
    endforeach()
    target_compile_definitions(cpu_startup_exe_linger_return PRIVATE RETURN_FROM_ENTRY)
    # Source-built CRT-free package: import the mapped DLL only by ordinal @77,
    # compare its native entry with pe_run_package, and reject a DLL exporting @78.
    foreach(variant IN ITEMS provider altered wrong live)
        if(variant STREQUAL "wrong")
            set(ord_def tests/cpu/package_ordinal_provider_wrong.def)
        else()
            set(ord_def tests/cpu/package_ordinal_provider.def)
        endif()
        add_library(cpu_package_ordinal_${variant} SHARED tests/cpu/package_ordinal_provider.cpp ${ord_def})
        target_compile_options(cpu_package_ordinal_${variant} PRIVATE /GS- /Zl)
        target_link_options(cpu_package_ordinal_${variant} PRIVATE /ENTRY:ordinal_provider_entry
            /NODEFAULTLIB /INCREMENTAL:NO)
    endforeach()
    target_compile_definitions(cpu_package_ordinal_altered PRIVATE ALTER_RETURN)
    # Control provider (#1375): mix_args leaves a thread running past the caller's entry point.
    target_compile_definitions(cpu_package_ordinal_live PRIVATE LIVE_WORKER)
    target_link_libraries(cpu_package_ordinal_live PRIVATE kernel32)
    # The _return control ends as before #1375: its entry point returns instead of ending the process.
    foreach(target IN ITEMS cpu_package_ordinal_exe cpu_package_ordinal_exe_return)
        add_executable(${target} tests/cpu/package_ordinal_exe.cpp)
        target_compile_options(${target} PRIVATE /GS- /Zl)
        target_link_options(${target} PRIVATE /ENTRY:ordinal_exe_entry
            /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE /INCREMENTAL:NO)
        target_link_libraries(${target} PRIVATE cpu_package_ordinal_provider)
    endforeach()
    target_compile_definitions(cpu_package_ordinal_exe_return PRIVATE RETURN_FROM_ENTRY)
    add_test(NAME cpu_native_package_ordinal_startup COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/package_ordinal_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_package_ordinal_exe>" "$<TARGET_FILE:cpu_package_ordinal_provider>"
        "$<TARGET_FILE:cpu_package_ordinal_altered>" "$<TARGET_FILE:cpu_package_ordinal_wrong>"
        "$<TARGET_FILE:cpu_package_ordinal_live>" "$<TARGET_FILE:cpu_package_ordinal_exe_return>")
    set_tests_properties(cpu_native_package_ordinal_startup PROPERTIES TIMEOUT 90)
    add_test(NAME pe_package_ordinal_plan COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_package_ordinal_plan_check.py")
    add_test(NAME cpu_native_startup COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_startup_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_startup_exe>" "$<TARGET_FILE:cpu_startup_a>" "$<TARGET_FILE:cpu_startup_b>"
        "$<TARGET_FILE:cpu_startup_b_noinit>" "$<TARGET_FILE:cpu_startup_a_alt>"
        "$<TARGET_FILE:cpu_startup_exe_timeout>" "$<TARGET_FILE:cpu_startup_exe_create>"
        "$<TARGET_FILE:cpu_startup_exe_linger>" "$<TARGET_FILE:cpu_startup_exe_linger_return>")
    # EXE-own TLS: a CRT-free EXE with a page-spanning initialized template and two TLS callbacks, launched
    # by Windows and started with pe_map_run; the startup log and exit code must match (Refs #165, #870).
    # The _early variant starts a thread inside its first process-attach callback (mapped only).
    foreach(target IN ITEMS cpu_exe_tls cpu_exe_tls_early)
        add_executable(${target} tests/cpu/exe_tls.cpp tests/cpu/exe_tls_template.asm)
        target_compile_options(${target} PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:/GS-;/Zl;/Zc:tlsGuards->")
        target_link_options(${target} PRIVATE /ENTRY:exe_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE
            /INCREMENTAL:NO)
        target_link_libraries(${target} PRIVATE kernel32)
    endforeach()
    target_compile_definitions(cpu_exe_tls_early PRIVATE EARLY_THREAD)
    add_test(NAME cpu_native_exe_tls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_exe_tls_check.py" "$<TARGET_FILE:pe_map>" "$<TARGET_FILE:cpu_exe_tls>"
        "$<TARGET_FILE:cpu_exe_tls_early>")
    # Main-image TLS slot 0: a CRT-free /GA EXE whose thread-locals are read through slot 0, launched by
    # Windows and started by a CRT-free host that owns slot 0 itself, with pe_map_run_main and explicit
    # participants and, as the control, pe_map_run (Refs #870, #165).
    # The _pause variant leaves a worker paused inside the image for the release refusal (mapped only). The
    # _enroll variant starts a probe worker whose enrollment or installation the host makes fail.
    foreach(target IN ITEMS cpu_exe_tls_slot0 cpu_exe_tls_slot0_pause cpu_exe_tls_slot0_enroll)
        add_executable(${target} tests/cpu/exe_tls_slot0.cpp tests/cpu/exe_tls_template.asm)
        target_compile_definitions(${target} PRIVATE $<$<COMPILE_LANGUAGE:ASM_MASM>:TLS_SLOT0_ARRAY>)
        target_compile_options(${target} PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:/GS-;/Zl;/GA;/Zc:tlsGuards->")
        target_link_options(${target} PRIVATE /ENTRY:exe_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE /DYNAMICBASE
            /INCREMENTAL:NO)
        target_link_libraries(${target} PRIVATE kernel32)
    endforeach()
    target_compile_definitions(cpu_exe_tls_slot0_pause PRIVATE PAUSED_WORKER)
    target_compile_definitions(cpu_exe_tls_slot0_enroll PRIVATE ENROLL_PROBE)
    add_executable(cpu_exe_tls_slot0_host tests/cpu/exe_tls_slot0_host.cpp)
    target_compile_options(cpu_exe_tls_slot0_host PRIVATE /GS- /Zl)
    target_link_options(cpu_exe_tls_slot0_host PRIVATE /ENTRY:host_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE
        /DYNAMICBASE /INCREMENTAL:NO)
    target_link_libraries(cpu_exe_tls_slot0_host PRIVATE kernel32)
    # Separate evidence: the Windows launch, and the pe_map scenarios with explicit participants.
    add_test(NAME cpu_native_exe_tls_slot0_windows COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_exe_tls_slot0_check.py" windows "$<TARGET_FILE:cpu_exe_tls_slot0>")
    add_test(NAME cpu_native_exe_tls_slot0 COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_exe_tls_slot0_check.py" mapped "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_tls_slot0>" "$<TARGET_FILE:cpu_exe_tls_slot0_host>"
        "$<TARGET_FILE:cpu_exe_tls_slot0_pause>")
    # Guest-thread enrollment failures, one child host process each: the probe worker's start routine must
    # never run, and the host must survive.
    add_test(NAME cpu_native_exe_tls_slot0_enroll COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_exe_tls_slot0_check.py" enroll "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_tls_slot0_enroll>" "$<TARGET_FILE:cpu_exe_tls_slot0_host>")
    # The mapped main EXE is the process image: GetModuleHandle(NULL) and FindResource(NULL, ...) find it.
    add_executable(cpu_exe_process_image tests/cpu/exe_process_image.cpp tests/cpu/exe_process_image.rc)
    target_compile_options(cpu_exe_process_image PRIVATE /GS- /Zl)
    target_link_options(cpu_exe_process_image PRIVATE /ENTRY:exe_entry /NODEFAULTLIB /SUBSYSTEM:CONSOLE
        /DYNAMICBASE /INCREMENTAL:NO)
    target_link_libraries(cpu_exe_process_image PRIVATE kernel32)
    add_test(NAME cpu_native_process_image COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/process_image_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_process_image>")
    set_tests_properties(cpu_native_process_image PROPERTIES TIMEOUT 60)
    # pe_run_package starts the same /GA EXE as the package's main image; its log must equal the Windows launch.
    add_test(NAME cpu_package_main_image COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/package_main_image_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_exe_tls_slot0>")
    set_tests_properties(cpu_package_main_image PROPERTIES TIMEOUT 60)
    # Lifecycle fixtures: two DLLs with the static MSVC runtime (B imports A) and a CRT-free event sink.
    add_library(cpu_life_sink SHARED tests/cpu/life_sink.cpp)
    target_compile_options(cpu_life_sink PRIVATE /GS- /Zl)
    target_link_options(cpu_life_sink PRIVATE /ENTRY:sink_main /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_life_sink PRIVATE kernel32)
    foreach(dll IN ITEMS a a_noctor b b_nodtor)
        string(REGEX REPLACE "_(noctor|nodtor)$" "" source "${dll}")
        add_library(cpu_life_${dll} SHARED tests/cpu/life_${source}.cpp)
        set_target_properties(cpu_life_${dll} PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreaded)
        target_link_options(cpu_life_${dll} PRIVATE /INCREMENTAL:NO)  # no incremental thunk in front of the entry point
        target_link_libraries(cpu_life_${dll} PRIVATE cpu_life_sink)
    endforeach()
    target_compile_definitions(cpu_life_a_noctor PRIVATE NO_CTOR)
    target_compile_definitions(cpu_life_b_nodtor PRIVATE NO_DTOR)
    target_link_libraries(cpu_life_b PRIVATE cpu_life_a)
    target_link_libraries(cpu_life_b_nodtor PRIVATE cpu_life_a)
    add_test(NAME cpu_native_crt_lifecycle COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_crt_lifecycle_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_life_sink>" "$<TARGET_FILE:cpu_life_a>" "$<TARGET_FILE:cpu_life_b>"
        "$<TARGET_FILE:cpu_life_a_noctor>" "$<TARGET_FILE:cpu_life_b_nodtor>")
    add_library(cpu_frame_host SHARED tests/cpu/frame_host.cpp)
    add_library(cpu_frame_guest SHARED tests/cpu/tls_route.asm tests/cpu/frame_route.def)
    set_target_properties(cpu_frame_guest PROPERTIES LINKER_LANGUAGE CXX)
    target_compile_definitions(cpu_frame_guest PRIVATE FRAME_GUEST)
    target_link_options(cpu_frame_guest PRIVATE /ENTRY:dll_entry /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_frame_guest PRIVATE cpu_tls_sink cpu_frame_host)

    add_library(cpu_delay_provider SHARED tests/cpu/delay_provider.cpp tests/cpu/delay_provider.def)
    add_library(cpu_delay_provider_altered SHARED tests/cpu/delay_provider.cpp
        tests/cpu/delay_provider_altered.def)
    target_compile_definitions(cpu_delay_provider_altered PRIVATE ALTER_RETURN)
    add_library(cpu_delay_route SHARED tests/cpu/delay_route.cpp)
    target_link_libraries(cpu_delay_route PRIVATE cpu_delay_provider delayimp)
    target_link_options(cpu_delay_route PRIVATE /DELAYLOAD:cpu_delay_provider.dll /INCREMENTAL:NO)
    add_test(NAME cpu_native_delay COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_delay_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_delay_route>" "$<TARGET_FILE:cpu_delay_provider>"
        "$<TARGET_FILE:cpu_delay_provider_altered>")
    add_library(cpu_tools_mem_provider SHARED tests/cpu/tools_mem_provider.cpp tests/cpu/tools_mem_provider.def)
    add_library(cpu_tools_mem_provider_devkit SHARED tests/cpu/tools_mem_provider.cpp
        tests/cpu/tools_mem_provider_devkit.def)
    target_compile_definitions(cpu_tools_mem_provider_devkit PRIVATE TOOLS_PARTITION_PRESENT)
    add_executable(cpu_tools_mem_caller tests/cpu/tools_mem_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_tools_mem_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_tools_mem_caller PRIVATE /ENTRY:native_startup /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_tools_mem_caller PRIVATE cpu_exe_io cpu_tools_mem_provider)
    add_test(NAME cpu_native_tools_mem COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/tools_mem_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_tools_mem_caller>" "$<TARGET_FILE:cpu_tools_mem_provider>"
        "$<TARGET_FILE:cpu_tools_mem_provider_devkit>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_tools_mem PROPERTIES TIMEOUT 60)

    add_library(cpu_map_pages_provider SHARED tests/cpu/map_pages_provider.cpp tests/cpu/map_pages_provider.def)
    add_executable(cpu_map_pages_caller tests/cpu/map_pages_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_map_pages_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_map_pages_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_map_pages_caller PRIVATE cpu_map_pages_provider cpu_exe_io)
    add_test(NAME cpu_native_map_pages COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/map_pages_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_map_pages_caller>" "$<TARGET_FILE:cpu_map_pages_provider>"
        "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_map_pages PROPERTIES TIMEOUT 60)

    add_library(cpu_transfer_mem_provider SHARED tests/cpu/transfer_mem_provider.cpp tests/cpu/transfer_mem_provider.def)
    add_executable(cpu_transfer_mem_caller tests/cpu/transfer_mem_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_transfer_mem_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_transfer_mem_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_transfer_mem_caller PRIVATE cpu_transfer_mem_provider cpu_exe_io)
    add_test(NAME cpu_native_transfer_mem COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/transfer_mem_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_transfer_mem_caller>" "$<TARGET_FILE:cpu_transfer_mem_provider>"
        "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_transfer_mem PROPERTIES TIMEOUT 60)

    add_library(cpu_transfer_chain_provider SHARED tests/cpu/transfer_chain_provider.cpp tests/cpu/transfer_chain_provider.def)
    add_executable(cpu_transfer_chain_caller tests/cpu/transfer_chain_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_transfer_chain_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_transfer_chain_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_transfer_chain_caller PRIVATE cpu_transfer_chain_provider cpu_exe_io)
    add_test(NAME cpu_native_transfer_chain COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/transfer_chain_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_transfer_chain_caller>" "$<TARGET_FILE:cpu_transfer_chain_provider>"
        "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_transfer_chain PROPERTIES TIMEOUT 60)

    add_library(cpu_apu_alloc_provider SHARED tests/cpu/apu_alloc_provider.cpp tests/cpu/apu_alloc_provider.def)
    add_library(cpu_apu_alloc_provider_lenient SHARED tests/cpu/apu_alloc_provider.cpp tests/cpu/apu_alloc_provider.def)
    target_compile_definitions(cpu_apu_alloc_provider_lenient PRIVATE APU_TEST_LENIENT)
    add_executable(cpu_apu_alloc_caller tests/cpu/apu_alloc_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_apu_alloc_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_apu_alloc_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_apu_alloc_caller PRIVATE cpu_apu_alloc_provider cpu_exe_io)
    add_test(NAME cpu_native_apu_alloc_caller COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/apu_alloc_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_apu_alloc_caller>" "$<TARGET_FILE:cpu_apu_alloc_provider>"
        "$<TARGET_FILE:cpu_apu_alloc_provider_lenient>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_apu_alloc_caller PROPERTIES TIMEOUT 60)

    add_library(cpu_apu_address_provider SHARED tests/cpu/apu_address_provider.cpp tests/cpu/apu_address_provider.def)
    add_library(cpu_apu_address_provider_faulty SHARED tests/cpu/apu_address_provider.cpp tests/cpu/apu_address_provider.def)
    target_compile_definitions(cpu_apu_address_provider_faulty PRIVATE APU_TEST_FAULTY)
    add_executable(cpu_apu_address_caller tests/cpu/apu_address_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_apu_address_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_apu_address_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_apu_address_caller PRIVATE cpu_apu_address_provider cpu_exe_io)
    add_test(NAME cpu_native_apu_address COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/apu_address_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_apu_address_caller>" "$<TARGET_FILE:cpu_apu_address_provider>"
        "$<TARGET_FILE:cpu_apu_address_provider_faulty>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_apu_address PROPERTIES TIMEOUT 60)

    add_library(cpu_acphal_hal_provider SHARED tests/cpu/acphal_hal_provider.cpp tests/cpu/acphal_hal_provider.def)
    add_library(cpu_acphal_hal_provider_faulty SHARED tests/cpu/acphal_hal_provider.cpp tests/cpu/acphal_hal_provider.def)
    target_compile_definitions(cpu_acphal_hal_provider_faulty PRIVATE ACPHAL_TEST_FAULTY)
    add_executable(cpu_acphal_hal_caller tests/cpu/acphal_hal_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_acphal_hal_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_acphal_hal_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_acphal_hal_caller PRIVATE cpu_acphal_hal_provider cpu_exe_io)
    add_test(NAME cpu_native_acphal_hal COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/acphal_hal_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_acphal_hal_caller>" "$<TARGET_FILE:cpu_acphal_hal_provider>"
        "$<TARGET_FILE:cpu_acphal_hal_provider_faulty>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_acphal_hal PROPERTIES TIMEOUT 60)

    add_library(cpu_gameinput_provider SHARED tests/cpu/gameinput_provider.cpp tests/cpu/gameinput_provider.def)
    foreach(variant IN ITEMS create_fail other_thread shifted_layout)
        string(TOUPPER "${variant}" variant_define)
        add_library(cpu_gameinput_provider_${variant} SHARED
            tests/cpu/gameinput_provider.cpp tests/cpu/gameinput_provider.def)
        target_compile_definitions(cpu_gameinput_provider_${variant} PRIVATE GAMEINPUT_TEST_${variant_define})
    endforeach()
    add_library(cpu_gameinput_provider_wrong SHARED tests/cpu/gameinput_provider.cpp tests/cpu/gameinput_provider_wrong.def)
    add_executable(cpu_gameinput_caller tests/cpu/gameinput_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_gameinput_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_gameinput_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_gameinput_caller PRIVATE cpu_gameinput_provider cpu_exe_io)
    add_test(NAME cpu_native_gameinput COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/gameinput_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_gameinput_caller>" "$<TARGET_FILE:cpu_gameinput_provider>"
        "$<TARGET_FILE:cpu_gameinput_provider_create_fail>" "$<TARGET_FILE:cpu_gameinput_provider_other_thread>"
        "$<TARGET_FILE:cpu_gameinput_provider_shifted_layout>" "$<TARGET_FILE:cpu_gameinput_provider_wrong>"
        "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_gameinput PROPERTIES TIMEOUT 120)

    add_library(cpu_xapu_queue_provider SHARED tests/cpu/xapu_queue_provider.cpp tests/cpu/xapu_queue_provider.def)
    add_library(cpu_xapu_queue_provider_lenient SHARED tests/cpu/xapu_queue_provider.cpp tests/cpu/xapu_queue_provider.def)
    target_compile_definitions(cpu_xapu_queue_provider_lenient PRIVATE XAPU_TEST_LENIENT)
    add_library(cpu_xapu_queue_provider_lifo SHARED tests/cpu/xapu_queue_provider.cpp tests/cpu/xapu_queue_provider.def)
    target_compile_definitions(cpu_xapu_queue_provider_lifo PRIVATE XAPU_TEST_LIFO)
    add_executable(cpu_xapu_queue_caller tests/cpu/xapu_queue_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_xapu_queue_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_xapu_queue_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_xapu_queue_caller PRIVATE cpu_xapu_queue_provider cpu_exe_io)
    add_test(NAME cpu_native_xapu_queue COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/xapu_queue_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_xapu_queue_caller>" "$<TARGET_FILE:cpu_xapu_queue_provider>"
        "$<TARGET_FILE:cpu_xapu_queue_provider_lenient>" "$<TARGET_FILE:cpu_xapu_queue_provider_lifo>"
        "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_xapu_queue PROPERTIES TIMEOUT 60)

    add_library(cpu_dstorage_provider SHARED tests/cpu/dstorage_provider.cpp tests/cpu/dstorage_provider.def)
    add_executable(cpu_dstorage_caller tests/cpu/dstorage_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_dstorage_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_dstorage_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_dstorage_caller PRIVATE cpu_dstorage_provider cpu_exe_io)
    add_test(NAME cpu_native_dstorage COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/dstorage_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_dstorage_caller>" "$<TARGET_FILE:cpu_dstorage_provider>"
        "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_dstorage PROPERTIES TIMEOUT 60)

    add_library(cpu_frame_events_provider SHARED tests/cpu/frame_events_provider.cpp tests/cpu/frame_events_provider.def)
    add_library(cpu_frame_events_provider_clobber SHARED tests/cpu/frame_events_provider.cpp tests/cpu/frame_events_provider.def)
    target_compile_definitions(cpu_frame_events_provider_clobber PRIVATE FAULT_CLOBBER)
    add_library(cpu_frame_events_provider_early SHARED tests/cpu/frame_events_provider.cpp tests/cpu/frame_events_provider.def)
    target_compile_definitions(cpu_frame_events_provider_early PRIVATE FAULT_EARLY_RELEASE)
    add_executable(cpu_frame_events_caller tests/cpu/frame_events_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_frame_events_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_frame_events_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_frame_events_caller PRIVATE cpu_frame_events_provider cpu_exe_io)
    add_test(NAME cpu_native_frame_events COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/frame_events_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_frame_events_caller>" "$<TARGET_FILE:cpu_frame_events_provider>"
        "$<TARGET_FILE:cpu_frame_events_provider_clobber>"
        "$<TARGET_FILE:cpu_frame_events_provider_early>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_frame_events PROPERTIES TIMEOUT 60)

    add_library(cpu_xg_swizzle_provider SHARED tests/cpu/xg_swizzle_provider.cpp tests/cpu/xg_swizzle_provider.def)
    add_library(cpu_xg_swizzle_provider_clobber SHARED tests/cpu/xg_swizzle_provider.cpp tests/cpu/xg_swizzle_provider.def)
    target_compile_definitions(cpu_xg_swizzle_provider_clobber PRIVATE FAULT_CLOBBER)
    add_library(cpu_xg_swizzle_provider_linear SHARED tests/cpu/xg_swizzle_provider.cpp tests/cpu/xg_swizzle_provider.def)
    target_compile_definitions(cpu_xg_swizzle_provider_linear PRIVATE FAULT_LINEAR)
    add_executable(cpu_xg_swizzle_caller tests/cpu/xg_swizzle_caller.asm tests/cpu/exe_startup.asm)
    set_target_properties(cpu_xg_swizzle_caller PROPERTIES LINKER_LANGUAGE CXX)
    target_link_options(cpu_xg_swizzle_caller PRIVATE /ENTRY:native_startup /EXPORT:native_entry /SUBSYSTEM:CONSOLE /NODEFAULTLIB /INCREMENTAL:NO)
    target_link_libraries(cpu_xg_swizzle_caller PRIVATE cpu_xg_swizzle_provider cpu_exe_io)
    add_test(NAME cpu_native_xg_swizzle COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/xg_swizzle_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_xg_swizzle_caller>" "$<TARGET_FILE:cpu_xg_swizzle_provider>"
        "$<TARGET_FILE:cpu_xg_swizzle_provider_clobber>"
        "$<TARGET_FILE:cpu_xg_swizzle_provider_linear>" "$<TARGET_FILE:cpu_exe_io>")
    set_tests_properties(cpu_native_xg_swizzle PROPERTIES TIMEOUT 60)
    add_test(NAME cpu_native_lifetime COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu/native_lifetime_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:cpu_tls_original>" "$<TARGET_FILE:cpu_tls_sink>")
    add_library(script_path_host SHARED tools/script_path_host.cpp)
    target_compile_features(script_path_host PRIVATE cxx_std_17)
    add_test(NAME script_path_links COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/script_path_check.py" "$<TARGET_FILE:script_path_host>")
    add_executable(ffx_pass26_lds tests/ffx_pass26_lds/gate.cpp)
    target_link_libraries(ffx_pass26_lds PRIVATE d3d11 d3dcompiler)
    add_test(NAME ffx_immediate_float_to_int_warp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_dispatch_aot_check.py" --immediate "${DXC_EXECUTABLE}" $<TARGET_FILE:offscreen_check> warp)
    add_test(NAME ffx_float_to_int_warp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_dispatch_aot_check.py" --readback $<TARGET_FILE:ffx_pass26_lds> warp)
    add_test(NAME ffx_float_math_warp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_dispatch_aot_check.py" --readback-float-math $<TARGET_FILE:ffx_pass26_lds> warp)
    add_test(NAME ffx_pass26_lds_warp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_pass26_lds/verify.py"
        --host $<TARGET_FILE:ffx_pass26_lds> --backend warp)
    add_test(NAME ffx_dispatch_profile_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_dispatch_profile_check.py")
    add_test(NAME ffx_dispatch_profile_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_dispatch_profile_cli_check.py")
    add_test(NAME ffx_dispatch_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_dispatch_aot_cli_check.py")
    add_test(NAME sampled_coverage_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/sampled_coverage_aot_cli_check.py")

    add_test(NAME script_state_literals COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/script_state_check.py")
    add_test(NAME resource_relocated_root COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/resource_root_check.py")
    add_test(NAME runtime_resource_root_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/resource_root_cli_check.py")
    add_test(NAME pe_authentihash COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_authentihash_check.py")
    add_test(NAME pe_authentihash_oracle COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_authentihash_oracle_check.py" "$<TARGET_FILE:xmem_shim>")
    set_tests_properties(pe_authentihash_oracle PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME pe_authentihash_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_authentihash_cli_check.py")
    add_test(NAME script_dispatch_pairs COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/script_dispatch_check.py" "$<TARGET_FILE:script_path_host>")
    add_test(NAME script_state_probe_checks COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/script_state_probe_check.py")
    add_test(NAME script_state_probe_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/script_state_probe_cli_check.py")
    set_tests_properties(script_state_probe_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME script_typed_path_dispatch COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/script_dispatch_check.py" "$<TARGET_FILE:script_path_host>" TypedScriptPathTests)
    add_test(NAME bcpack_prefix_and_mip_tail COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bcpack_check.py")
    add_test(NAME bcpack_rans_symbols COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bcpack_symbols_check.py")
    add_test(NAME bcpack_symbols_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bcpack_symbols_cli_check.py")
    set_tests_properties(bcpack_symbols_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME bcpack_tables COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bcpack_tables_check.py")
    add_test(NAME bcpack_probe_cli COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bcpack_probe_cli_check.py")
    add_test(NAME bc7_block_reference COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bc7_blocks_check.py")
    add_test(NAME bc7_tile_swizzle COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bc7_tiles_check.py")
    add_test(NAME gfx10_texture_roundtrip COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/gfx10_texture_roundtrip_check.py" roundtrip)
    add_test(NAME gfx10_texture_roundtrip_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/gfx10_texture_roundtrip_check.py" controls)
    add_test(NAME texture_bc_volume COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/texture_bc_volume_check.py")
    add_test(NAME bc7_blocks_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bc7_blocks_cli_check.py")
    add_test(NAME texture_descriptors_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/texture_descriptors_check.py")
    add_test(NAME textures_texture_descriptors_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/texture_descriptors_cli_check.py")
    set_tests_properties(textures_texture_descriptors_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME resource_range_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/resource_ranges_check.py")
    add_test(NAME ttpf_batch_export COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ttpf_batch_export_check.py")
    add_test(NAME ttpf_batch_export_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ttpf_batch_export_cli_check.py")
    add_test(NAME audio_awc_metadata COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/awc_metadata_check.py")
    add_test(NAME audio_awc_metadata_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/awc_metadata_cli_check.py")
    add_test(NAME sgd5_effect_candidates COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/sgd5_effects_check.py")
    add_test(NAME pixel_aot_sample_clamp_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pixel_sample_clamp_check.py")
    add_test(NAME pixel_aot_sample_clamp_compile COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pixel_sample_clamp_check.py" compile "${DXC_EXECUTABLE}")
    set_tests_properties(pixel_aot_sample_clamp_compile PROPERTIES TIMEOUT 90)
    add_test(NAME shader_sgd5_effects_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/sgd5_effects_cli_check.py")
    set_tests_properties(shader_sgd5_effects_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME rdna2_tools_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/rdna2_tools_check.py")
    add_test(NAME rdna2_cli_checks COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/disasm_rdna2_cli_check.py")
    add_test(NAME pso_readiness_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pso_readiness_check.py")
    add_test(NAME shader_pso_readiness_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pso_readiness_cli_check.py")
    add_test(NAME dxcontainer_part_offsets COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/dxcontainer_part_offsets_check.py")
    add_test(NAME depth_mask_aot_cli COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/depth_mask_aot_cli_check.py")
    add_test(NAME extract_shaders_cli COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/extract_shaders_cli_check.py")
    # #369: the built cs_6_0 array-atomics probe keeps nonUniformIndex on its atomic's handle.
    add_test(NAME array_atomics_dxil COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/array_atomics_dxil_check.py" "${DXC_EXECUTABLE}"
        "${CMAKE_CURRENT_BINARY_DIR}/ProbeArrayAtomics.cso" "${CMAKE_SOURCE_DIR}/tests/gpu_alias_writes.hlsl"
        "${CMAKE_SOURCE_DIR}/src")
    add_test(NAME mesh_dynamic_geometry_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_dynamic_geometry_check.py")
    add_test(NAME mesh_heap_sampler_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_heap_sampler_check.py")
    add_test(NAME mesh_clip_cull_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_clip_cull_check.py")
    add_test(NAME mesh_dynamic_aot_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_dynamic_aot_check.py")
    add_test(NAME mesh_dynamic_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_dynamic_aot_cli_check.py")
    add_test(NAME mesh_lane_spill_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_lane_spill_check.py")
    add_test(NAME mesh_entry_skipped_scalar_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" skipped)
    add_test(NAME mesh_entry_flat_scratch_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" flat-scratch)
    add_test(NAME mesh_scc_any_lane_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_scc_any_lane_check.py")
    add_test(NAME mesh_loop_census COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_loop_census_check.py")
    add_test(NAME mesh_loop_census_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_loop_census_cli_check.py")
    add_test(NAME mesh_entry_exec_restore_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" exec-restore)
    add_test(NAME mesh_amplification_refusal COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_amplification_refusal_check.py")
    set_tests_properties(mesh_amplification_refusal PROPERTIES TIMEOUT 30)
    add_test(NAME mesh_entry_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_entry_aot_cli_check.py")
    add_test(NAME mesh_bitcmp_clause_cpu COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/mesh_bitcmp_clause_check.py")
    foreach(adapter IN ITEMS hardware warp)
        add_test(NAME mesh_dynamic_aot_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_dynamic_aot_draw_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_dynamic_aot_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
        add_test(NAME mesh_scc_any_lane_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_scc_any_lane_draw_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_scc_any_lane_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
        add_test(NAME mesh_two_exits_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_two_exits_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_two_exits_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_pixel_pipeline_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_pixel_pipeline_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_pixel_pipeline_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_mesh57_skeleton_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_skeleton_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_mesh57_skeleton_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_mesh57_loop_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_loop_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_mesh57_loop_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_mesh57_lane_spill_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_lane_spill_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_mesh57_lane_spill_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_mesh57_skeleton_wave_shift_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_skeleton_check.py" shift "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_mesh57_skeleton_wave_shift_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        # A slot 57 pair whose pixel stage exports only to the null target, drawn depth-only (#2413 T5).
        add_test(NAME startup_mesh57_skeleton_depth_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_skeleton_check.py" depth "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_mesh57_skeleton_depth_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        # A slot 57 colour pair whose pixel stage leaves a kill through the early-exit null export (#2413).
        add_test(NAME startup_mesh57_skeleton_kill_exit_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_skeleton_check.py" killexit "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_mesh57_skeleton_kill_exit_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_mesh57_formatted_load_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_skeleton_check.py" formatted "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_mesh57_formatted_load_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_mesh57_skeleton_exchange_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_mesh57_skeleton_check.py" exchange "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} "$<TARGET_FILE:startup_indirect_draw_indexed>")
        set_tests_properties(startup_mesh57_skeleton_exchange_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_cbv_order_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_cbv_order_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_cbv_order_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_descriptor_swap_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_descriptor_swap_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_descriptor_swap_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_join_descriptor_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_join_descriptor_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_join_descriptor_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_indexed_fallback_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_fallback_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_indexed_fallback_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_indexed_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_indexed_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_indexed_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        # Several vertices and triangles in one mesh allocation, up to 128 of each across both waves (#730).
        add_test(NAME mesh_multi_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_multi_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_multi_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_attribute_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_attribute_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_attribute_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_textured_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_textured_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_textured_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_textured_fallback_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_textured_check.py" fallback "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_textured_fallback_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME compute_mesh_texture_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mesh_texture_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_mesh_texture_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME compute_mesh_texture_fallback_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mesh_texture_check.py" fallback "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_mesh_texture_fallback_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        # #810: default and -Od DXIL of the same source-built mesh shader through one PSO harness.
        add_test(NAME mesh_od_pipeline_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tools/mesh_od_pipeline.py" --check --dxc "${DXC_EXECUTABLE}"
            --renderer "$<TARGET_FILE:offscreen_check>" --adapter ${adapter}
            --seed 0x5eed0001 --compile-timeout 30 --pipeline-timeout 30)
        set_tests_properties(mesh_od_pipeline_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        if(adapter STREQUAL "hardware")
            add_test(NAME mesh_od_pipeline_check COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/mesh_od_pipeline_check.py")
            set_tests_properties(mesh_od_pipeline_check PROPERTIES TIMEOUT 30)
            add_test(NAME mesh_od_pipeline_cli_check COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/mesh_od_pipeline_cli_check.py")
            set_tests_properties(mesh_od_pipeline_cli_check PROPERTIES TIMEOUT 30)
        endif()
        add_test(NAME mesh_depth_pair_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_depth_pair_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_depth_pair_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_depth_pair_fallback_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_depth_pair_check.py" fallback "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_depth_pair_fallback_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_heap_sampler_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_heap_sampler_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_heap_sampler_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
        add_test(NAME mesh_lit_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_lit_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_lit_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_lit_fallback_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_lit_check.py" fallback "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_lit_fallback_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_shadow_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_shadow_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_shadow_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        # Clip and cull distances in pos1/pos2, placed by an explicit PA_CL_VS_OUT_CNTL word (#1998 item F).
        add_test(NAME mesh_clip_cull_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_clip_cull_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_clip_cull_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
        add_test(NAME mesh_entry_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_entry_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_entry_skipped_scalar_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" draw-skipped "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_entry_skipped_scalar_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_entry_float_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" draw-float "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_entry_float_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_entry_cvt_minmax_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" draw-cvt-minmax "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_entry_cvt_minmax_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_entry_exec_restore_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" draw-exec-restore "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_entry_exec_restore_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_entry_unary_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_entry_check.py" draw-unary "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_entry_unary_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME mesh_amplified_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/mesh_amplified_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(mesh_amplified_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME compute_store_aot_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_${adapter}.txt")
        # A whole-register immediate write to the scratch base must leave the indexed kernel's HLSL and its
        # readback unchanged, guards included (#1648).
        add_test(NAME compute_store_aot_scratch_base_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-scratch-base-write "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_scratch_base_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_scratch_base_${adapter}.txt")
        # Entry registers from COMPUTE_PGM_RSRC2: user SGPRs, group IDs and local IDs (#1544).
        add_test(NAME compute_entry_layout_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_entry_layout_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_entry_layout_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME compute_store_aot_dpp_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-dpp "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_dpp_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_dpp_${adapter}.txt")
        add_test(NAME compute_store_aot_readlane_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-readlane "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_readlane_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_readlane_${adapter}.txt")
        # DPP16 row_shr with and without BOUND_CTRL on 16-lane logical rows (#1543).
        add_test(NAME compute_store_aot_dpp_row_shr_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_dpp_row_shr_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_dpp_row_shr_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_dpp_row_shr_${adapter}.txt")
        add_test(NAME compute_store_aot_guard_read_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-guard-read "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_guard_read_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_guard_read_${adapter}.txt")
        # Keep the full guarded-read differential and its negative controls on slower hardware.
        if(adapter STREQUAL "hardware")
            set_tests_properties(compute_store_aot_guard_read_hardware PROPERTIES TIMEOUT 180)
        endif()
        add_test(NAME compute_store_aot_mubuf_subword_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-subword "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_subword_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_subword_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_vop1_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_vop1_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_vop1_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_vop1_${adapter}.txt")
        add_test(NAME compute_store_aot_f32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-f32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_f32_${adapter} PROPERTIES TIMEOUT 60
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_f32_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_bfm_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_bfm_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_bfm_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_bfm_${adapter}.txt")
        add_test(NAME compute_store_aot_cvt_u32_f32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-cvt-u32-f32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_cvt_u32_f32_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_cvt_u32_f32_${adapter}.txt")
        add_test(NAME compute_store_aot_mbcnt_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mbcnt "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mbcnt_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mbcnt_${adapter}.txt")
        add_test(NAME compute_store_aot_bcnt_exec_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-bcnt-exec "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_bcnt_exec_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_bcnt_exec_${adapter}.txt")
        add_test(NAME compute_store_aot_writelane_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-writelane "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_writelane_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_writelane_${adapter}.txt")
        add_test(NAME compute_store_aot_ff1_exec_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-ff1-exec "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_ff1_exec_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_ff1_exec_${adapter}.txt")
        add_test(NAME compute_store_aot_ff1_scalar_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-ff1-scalar "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_ff1_scalar_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_ff1_scalar_${adapter}.txt")
        add_test(NAME compute_store_aot_vadd_nc_i32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-vadd_nc_i32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_vadd_nc_i32_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_vadd_nc_i32_${adapter}.txt")
        add_test(NAME compute_store_aot_salu_i32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-salu_i32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_salu_i32_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_salu_i32_${adapter}.txt")
        add_test(NAME compute_store_aot_add_co_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-add-co "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_add_co_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_add_co_${adapter}.txt")
        add_test(NAME compute_store_aot_sub_co_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-sub-co "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_sub_co_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_sub_co_${adapter}.txt")
        add_test(NAME compute_store_aot_dot_u_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-dot-u "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_dot_u_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_dot_u_${adapter}.txt")
        add_test(NAME compute_store_aot_mac_f32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mac-f32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mac_f32_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mac_f32_${adapter}.txt")
        add_test(NAME compute_store_aot_bfe_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-bfe "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_bfe_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_bfe_${adapter}.txt")
        add_test(NAME compute_store_aot_vcmp_select_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-vcmp-select "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_vcmp_select_${adapter} PROPERTIES TIMEOUT 45
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_vcmp_select_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_reduction_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-reduction "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_reduction_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_reduction_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_buffer_atomics_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_buffer_atomics_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_buffer_atomics_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_buffer_atomics_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_minmax3_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_minmax3_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_minmax3_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_minmax3_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_reduction_x2_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-reduction-x2 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_reduction_x2_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_reduction_x2_${adapter}.txt")
        foreach(exchange IN ITEMS exchange exchange-x2)
            add_test(NAME compute_store_aot_mubuf_${exchange}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" "draw-mubuf-${exchange}" "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(compute_store_aot_mubuf_${exchange}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
                ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_${exchange}_${adapter}.txt")
        endforeach()
        foreach(counter IN ITEMS counter counter-x2)
            add_test(NAME compute_store_aot_mubuf_${counter}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" "draw-mubuf-${counter}" "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(compute_store_aot_mubuf_${counter}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
                ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_${counter}_${adapter}.txt")
        endforeach()
        add_test(NAME compute_store_aot_mubuf_csub_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-csub "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_csub_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_csub_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_float_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-float "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_float_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_float_${adapter}.txt")
        foreach(float_extra IN ITEMS float-cmpswap float-x2)
            add_test(NAME compute_store_aot_mubuf_${float_extra}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" "draw-mubuf-${float_extra}" "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(compute_store_aot_mubuf_${float_extra}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
                ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_${float_extra}_${adapter}.txt")
        endforeach()
        add_test(NAME compute_store_aot_mubuf_vector_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-vector "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_vector_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_vector_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_med3_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_med3_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_med3_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_med3_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_d16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-d16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_d16_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_d16_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_xor3_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_xor3_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_xor3_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_xor3_${adapter}.txt")
        add_test(NAME compute_store_aot_f32_negabs_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_negabs_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_f32_negabs_${adapter} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME compute_store_aot_alu_bcnt_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_bcnt_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_bcnt_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_bcnt_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_lane_gaps_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_lane_gaps_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_lane_gaps_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_lane_gaps_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_load_format_d16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-load-format-d16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_load_format_d16_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_load_format_d16_${adapter}.txt")
        add_test(NAME compute_store_aot_mtbuf_load_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mtbuf-load "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mtbuf_load_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mtbuf_load_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_mad_i24_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_mad_i24_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_mad_i24_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_mad_i24_${adapter}.txt")
        # A translated gfx1030 compute shader reads an R32G32B32A32_UINT texture through image_load and
        # stores the dmask-selected texel components; the harness compares all 320 UAV readback words.
        add_test(NAME compute_store_aot_mubuf_format_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-format "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_format_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_format_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_load_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-load "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_load_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_load_${adapter}.txt")
        add_test(NAME compute_store_aot_alu_cvt_pk_u8_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_alu_cvt_pk_u8_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_alu_cvt_pk_u8_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_alu_cvt_pk_u8_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_mip_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-mip "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_mip_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_mip_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_resinfo_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-resinfo "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_resinfo_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_resinfo_${adapter}.txt")
        add_test(NAME compute_store_aot_salu_absdiff_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_salu_absdiff_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_salu_absdiff_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_salu_absdiff_${adapter}.txt")
        add_test(NAME compute_store_aot_desc_numeric_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_desc_numeric_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_desc_numeric_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_desc_numeric_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_packed_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-packed "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_packed_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_packed_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_msaa_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mimg_msaa_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_msaa_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_msaa_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_image_store_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mimg_float_store_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_image_store_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_image_store_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_image_uav_load_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mimg_image_uav_load_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_image_uav_load_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_image_uav_load_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_image_store_layers_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mimg_float_store_layers_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_image_store_layers_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_image_store_layers_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_image_store_1d_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mimg_float_store_1d_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_image_store_1d_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_image_store_1d_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_image_store_d16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_mimg_float_store_d16_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_image_store_d16_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_image_store_d16_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_image_atomics_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_image_atomics_gfx1013_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_image_atomics_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_image_atomics_${adapter}.txt")
        add_test(NAME compute_store_aot_gfx1013_gather4_l_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_gather4_l_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_gfx1013_gather4_l_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_gfx1013_gather4_l_${adapter}.txt")
        add_test(NAME compute_store_aot_salu_bitset_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_salu_bitset_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_salu_bitset_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_salu_bitset_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_store_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-store "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_store_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_store_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_store_packed_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-packed-store "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_store_packed_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_store_packed_${adapter}.txt")
        add_test(NAME compute_store_aot_lane_mask_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_lane_mask_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lane_mask_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lane_mask_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_atomic_integer_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-atomic-integer "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_atomic_integer_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_atomic_integer_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_atomic_minmax_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-atomic-minmax "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_atomic_minmax_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_atomic_minmax_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_atomic_exchange_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-atomic-exchange "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_atomic_exchange_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_atomic_exchange_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_atomic_counter_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-atomic-counter "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_atomic_counter_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_atomic_counter_${adapter}.txt")
        add_test(NAME compute_store_aot_mimg_atomic_float_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mimg-atomic-float "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mimg_atomic_float_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mimg_atomic_float_${adapter}.txt")
        add_test(NAME compute_store_aot_ds_route_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-ds-route "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_ds_route_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_ds_route_${adapter}.txt")
        add_test(NAME compute_store_aot_lds_private_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-private "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lds_private_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_private_${adapter}.txt")
        add_test(NAME compute_store_aot_lds_shared_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-shared "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lds_shared_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_shared_${adapter}.txt")
        add_test(NAME compute_store_aot_lds_packed_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-packed "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lds_packed_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_packed_${adapter}.txt")
        foreach(lds_case IN ITEMS arithmetic replacement)
            add_test(NAME compute_store_aot_lds_${lds_case}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-${lds_case} "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter})
            set_tests_properties(compute_store_aot_lds_${lds_case}_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
                ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_${lds_case}_${adapter}.txt")
        endforeach()
        add_test(NAME compute_store_aot_lds_strided_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-strided "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lds_strided_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_strided_${adapter}.txt")
        add_test(NAME compute_store_aot_lds_wide_replacement_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-wide-replacement "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lds_wide_replacement_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_wide_replacement_${adapter}.txt")
        add_test(NAME compute_store_aot_lds_qword_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-qword "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lds_qword_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_qword_${adapter}.txt")
        add_test(NAME compute_store_aot_lds_f32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-lds-f32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_lds_f32_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_lds_f32_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_store_format_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-format-store "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_store_format_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_store_format_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_store_format_xyz_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-format-store-xyz "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_store_format_xyz_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_store_format_xyz_${adapter}.txt")
        add_test(NAME compute_store_aot_descriptor_store_format_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-descriptor-store-format "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_descriptor_store_format_${adapter} PROPERTIES TIMEOUT 60
            SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_descriptor_store_format_${adapter}.txt")
        add_test(NAME compute_store_aot_descriptor_load_format_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_load_format_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_descriptor_load_format_${adapter} PROPERTIES TIMEOUT 120
            SKIP_RETURN_CODE 77)
        add_test(NAME compute_store_aot_descriptor_load_format_d16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_load_format_check.py" draw-d16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_descriptor_load_format_d16_${adapter} PROPERTIES TIMEOUT 120
            SKIP_RETURN_CODE 77)
        add_test(NAME compute_store_aot_heap_view_load_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_heap_view_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_heap_view_load_${adapter} PROPERTIES TIMEOUT 180
            SKIP_RETURN_CODE 77)
        add_test(NAME compute_store_aot_heap_view_store_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_heap_store_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_heap_view_store_${adapter} PROPERTIES TIMEOUT 120
            SKIP_RETURN_CODE 77)
        add_test(NAME compute_store_aot_mtbuf_store_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mtbuf-store "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mtbuf_store_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mtbuf_store_${adapter}.txt")
        add_test(NAME compute_store_aot_mubuf_store_subword_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_store_check.py" draw-mubuf-subword-store "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_store_aot_mubuf_store_subword_${adapter} PROPERTIES TIMEOUT 45 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/compute_store_aot_mubuf_store_subword_${adapter}.txt")
        add_test(NAME compute_to_pixel_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/compute_to_pixel_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(compute_to_pixel_${adapter} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
        add_test(NAME cpu_native_frame_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/cpu/native_frame_check.py" "$<TARGET_FILE:cpu_frame_guest>"
            "$<TARGET_FILE:cpu_tls_sink>" "$<TARGET_FILE:cpu_frame_host>" "$<TARGET_FILE:pe_map>"
            "${DXC_EXECUTABLE}" "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(cpu_native_frame_${adapter} PROPERTIES TIMEOUT 95)
        add_test(NAME pixel_aot_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-core "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_core_vector_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-core-vector "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_core_vector_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_core_vector_${adapter}.txt")
        add_test(NAME pixel_aot_dpp_cvt_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-dpp-cvt "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_dpp_cvt_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_dpp_cvt_${adapter}.txt")
        add_test(NAME pixel_aot_dpp_movrel_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-dpp-movrel "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_dpp_movrel_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_dpp_movrel_${adapter}.txt")
        add_test(NAME pixel_aot_plain_movrel_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-plain-movrel "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_plain_movrel_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_plain_movrel_${adapter}.txt")
        add_test(NAME pixel_aot_swaprel_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-swaprel "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_swaprel_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_swaprel_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_movrel_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-movrel "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_movrel_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_movrel_${adapter}.txt")
        add_test(NAME pixel_aot_smovrel_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-smovrel "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_smovrel_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_smovrel_${adapter}.txt")
        add_test(NAME pixel_aot_dpp_f16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-dpp-f16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_dpp_f16_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_dpp_f16_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_f16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-f16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_f16_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_f16_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_int_extra_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-int-extra "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_int_extra_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_int_extra_${adapter}.txt")
        add_test(NAME pixel_aot_f16_exact_extra_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-f16-exact-extra "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_f16_exact_extra_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_f16_exact_extra_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_cvt_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-cvt "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_cvt_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_cvt_${adapter}.txt")
        add_test(NAME pixel_aot_dpp_extra_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-dpp-extra "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_dpp_extra_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_dpp_extra_${adapter}.txt")
        add_test(NAME pixel_aot_compressed_export_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-compressed-export "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_compressed_export_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_uncompressed_export_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-uncompressed-export "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_uncompressed_export_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_uncompressed_integer_export_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-uncompressed-integer-export "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_uncompressed_integer_export_${adapter} PROPERTIES
            TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_ds_swizzle_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-ds-swizzle "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_ds_swizzle_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_ds_swizzle_${adapter}.txt")
        add_test(NAME pixel_aot_exec_regions_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-exec-regions "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_exec_regions_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_exec_regions_${adapter}.txt")
        add_test(NAME pixel_aot_scc_skip_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-scc-skip "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_scc_skip_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_scc_skip_${adapter}.txt")
        add_test(NAME pixel_aot_s_call_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-s-call "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_s_call_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_s_call_${adapter}.txt")
        add_test(NAME pixel_aot_cmpx_regions_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cmpx-regions "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cmpx_regions_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cmpx_regions_${adapter}.txt")
        add_test(NAME pixel_aot_cmpx_e64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cmpx-e64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cmpx_e64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cmpx_e64_${adapter}.txt")
        add_test(NAME pixel_aot_region_body_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-region-body "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_region_body_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_region_body_${adapter}.txt")
        add_test(NAME pixel_aot_region_waits_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-region-waits "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_region_waits_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_region_waits_${adapter}.txt")
        add_test(NAME pixel_aot_region_scalar_alu_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-region-scalar-alu "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_region_scalar_alu_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_region_scalar_alu_${adapter}.txt")
        add_test(NAME pixel_aot_region_scalar_load_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-region-scalar-load "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_region_scalar_load_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_region_scalar_load_${adapter}.txt")
        add_test(NAME pixel_position_centers_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_position_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_position_centers_${adapter} PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_buffer_color_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" buffer-color "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_buffer_color_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME depth_mask_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/depth_mask_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(depth_mask_draw_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME depth_mask_ops_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/depth_mask_check.py" ops "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(depth_mask_ops_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME depth_mask_cmpx_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/depth_mask_check.py" cmpx "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(depth_mask_cmpx_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME depth_mask_unary_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/depth_mask_check.py" unary "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(depth_mask_unary_draw_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_cb_read_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_cb_read_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_cb_read_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        foreach(control IN ITEMS debug removal)
            add_test(NAME pixel_batch_${control}_${adapter} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/pixel_batch_diagnostics_check.py" "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" ${adapter} ${control})
            set_tests_properties(pixel_batch_${control}_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        endforeach()
        add_test(NAME pixel_batch_pairs_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_batch_pairs_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_batch_pairs_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_u32_from_f32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_uint_conversion_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_u32_from_f32_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_u32_from_f32_${adapter}.txt")
        add_test(NAME sampled_coverage_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/sampled_coverage_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(sampled_coverage_${adapter} PROPERTIES TIMEOUT 150 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_attribute_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_attribute_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_attribute_${adapter} PROPERTIES TIMEOUT 45)
        # attr0.z/w read as plain values next to a sample at attr0.xy (#730).
        add_test(NAME pixel_aot_attribute_sampled_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_attribute_sampled_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_attribute_sampled_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_dmask_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_dmask_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_dmask_${adapter} PROPERTIES TIMEOUT 45)
        add_test(NAME pixel_aot_sample_lod_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_sample_lod_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sample_lod_${adapter} PROPERTIES TIMEOUT 60
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sample_lod_${adapter}.txt")
        add_test(NAME pixel_aot_sample_offset_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_sample_offset_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sample_offset_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sample_offset_${adapter}.txt")
        # Keep these desktop differential results out of opcode coverage until native gfx1030 is measured.
        add_test(NAME pixel_aot_sample_clamp_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_sample_clamp_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sample_clamp_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77 RUN_SERIAL TRUE)
        add_test(NAME pixel_aot_sample_gradient_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_sample_gradient_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sample_gradient_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sample_gradient_${adapter}.txt")
        add_test(NAME pixel_aot_sample_coarse_gradient_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_sample_gradient_check.py" draw-coarse "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sample_coarse_gradient_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sample_coarse_gradient_${adapter}.txt")
        add_test(NAME pixel_aot_three_way_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" three-way "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_three_way_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_predicate_rounding_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-predicate-rounding "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_predicate_rounding_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_comparisons_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-comparisons "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_comparisons_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_comparisons_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_cmp_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-cmp "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_cmp_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_cmp_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_int_compare_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-int-compare "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_int_compare_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_int_compare_${adapter}.txt")
        add_test(NAME pixel_aot_get_lod_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_get_lod_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_get_lod_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_get_lod_${adapter}.txt")
        add_test(NAME pixel_aot_blend_scalar_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-blend-scalar "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_blend_scalar_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_bfm_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-bfm "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_bfm_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_brev_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-brev "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_brev_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_brev_${adapter}.txt")
        add_test(NAME pixel_aot_smem_pointers_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-smem-pointers "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_smem_pointers_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_smem_pointers_${adapter}.txt")
        add_test(NAME pixel_aot_cmp64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cmp64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cmp64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cmp64_${adapter}.txt")
        add_test(NAME pixel_aot_cmp_f64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cmp-f64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cmp_f64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cmp_f64_${adapter}.txt")
        add_test(NAME pixel_aot_shift64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-shift64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_shift64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_shift64_${adapter}.txt")
        add_test(NAME pixel_aot_pk_fmac_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-pk-fmac "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_pk_fmac_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_pk_fmac_${adapter}.txt")
        add_test(NAME pixel_aot_plain_bitscan_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-plain-bitscan "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_plain_bitscan_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_int16_vop3_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-int16-vop3 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_int16_vop3_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_int16_ternary_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-int16-ternary "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_int16_ternary_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_f16_arith_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-f16-arith "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_f16_arith_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_f16_round_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-f16-round "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_f16_round_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_f16_fmac_ldexp_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-f16-fmac-ldexp "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_f16_fmac_ldexp_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_f16_cvt_int16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-f16-cvt-int16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_f16_cvt_int16_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_f16_to_int16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-f16-to-int16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_f16_to_int16_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_swap_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-swap "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_swap_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_swap_${adapter}.txt")
        add_test(NAME pixel_aot_cvt_float_int_e64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cvt-float-int-e64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cvt_float_int_e64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cvt_float_int_e64_${adapter}.txt")
        add_test(NAME pixel_aot_cvt_flr_rpi_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cvt-flr-rpi "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cvt_flr_rpi_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cvt_flr_rpi_${adapter}.txt")
        add_test(NAME pixel_aot_flat_scratch_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-flat-scratch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_flat_scratch_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_flat_scratch_${adapter}.txt")
        add_test(NAME pixel_aot_sopk_hwreg_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sopk-hwreg "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sopk_hwreg_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sopk_hwreg_${adapter}.txt")
        add_test(NAME pixel_aot_sopp_round_mode_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sopp-round-mode "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sopp_round_mode_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sopp_round_mode_${adapter}.txt")
        add_test(NAME pixel_aot_e64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-e64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_e64_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_e64_approx_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-e64-approx "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_e64_approx_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_e64_approx_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_unary_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-unary "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_unary_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_unary_${adapter}.txt")
        add_test(NAME pixel_aot_mac_legacy_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-mac-legacy "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_mac_legacy_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_mac_legacy_${adapter}.txt")
        add_test(NAME pixel_aot_integer_nc_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-integer-nc "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_integer_nc_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_title_loads_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-title-loads "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_title_loads_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_title_loads_${adapter}.txt")
        add_test(NAME pixel_aot_align_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-align "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_align_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_vop3_ternary_int_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-vop3-ternary-int "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_vop3_ternary_int_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME pixel_aot_e64_integer_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-e64-integer "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_e64_integer_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_e64_integer_${adapter}.txt")
        add_test(NAME pixel_aot_sdwa_integer_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sdwa-integer "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sdwa_integer_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sdwa_integer_${adapter}.txt")
        add_test(NAME pixel_aot_e64_spellings_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-e64-spellings "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_e64_spellings_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_e64_spellings_${adapter}.txt")
        add_test(NAME pixel_aot_vop1_nops_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-vop1-nops "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_vop1_nops_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_vop1_nops_${adapter}.txt")
        add_test(NAME pixel_aot_frexp_exp_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-frexp-exp "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_frexp_exp_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_frexp_exp_${adapter}.txt")
        add_test(NAME pixel_aot_first_bit_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-first-bit "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_first_bit_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_first_bit_${adapter}.txt")
        add_test(NAME pixel_aot_bitset64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-bitset64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_bitset64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_bitset64_${adapter}.txt")
        add_test(NAME pixel_aot_carry_out_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-carry-out "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_carry_out_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_carry_out_${adapter}.txt")
        add_test(NAME pixel_aot_carry_in_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-carry-in "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_carry_in_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_carry_in_${adapter}.txt")
        add_test(NAME pixel_aot_mad64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-mad64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_mad64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_mad64_${adapter}.txt")
        add_test(NAME pixel_aot_cvt_f64_int_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cvt-f64-int "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cvt_f64_int_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cvt_f64_int_${adapter}.txt")
        add_test(NAME pixel_aot_cvt_f64_f32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cvt-f64-f32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cvt_f64_f32_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cvt_f64_f32_${adapter}.txt")
        add_test(NAME pixel_aot_cvt_int_f64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cvt-int-f64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cvt_int_f64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cvt_int_f64_${adapter}.txt")
        add_test(NAME pixel_aot_cvt_f32_f64_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-cvt-f32-f64 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_cvt_f32_f64_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_cvt_f32_f64_${adapter}.txt")
        add_test(NAME pixel_aot_sad_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-sad "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_sad_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_sad_${adapter}.txt")
        add_test(NAME pixel_aot_rndne_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_rndne_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_rndne_${adapter} PROPERTIES TIMEOUT 60
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_rndne_${adapter}.txt")
        add_test(NAME pixel_aot_pack_int16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-pack-int16 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_pack_int16_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_pack_int16_${adapter}.txt")
        add_test(NAME pixel_aot_pack_b32_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-pack-b32 "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_pack_b32_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_pack_b32_${adapter}.txt")
        foreach(mode IN ITEMS level bias)
            set(test_name pixel_aot_compare_lod_${mode}_${adapter})
            add_test(NAME ${test_name} COMMAND "${INTAKE_PYTHON}" -B
                "${CMAKE_SOURCE_DIR}/tests/pixel_compare_lod_check.py" draw "${mode}" "${DXC_EXECUTABLE}"
                "$<TARGET_FILE:offscreen_check>" "${adapter}")
            set_tests_properties(${test_name} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
                ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/${test_name}.txt")
        endforeach()
        add_test(NAME pixel_aot_compare_grad_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_compare_grad_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" "${adapter}")
        set_tests_properties(pixel_aot_compare_grad_${adapter} PROPERTIES TIMEOUT 180 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_compare_grad_${adapter}.txt")
        add_test(NAME pixel_aot_compare_sample_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_compare_sample_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" "${adapter}")
        set_tests_properties(pixel_aot_compare_sample_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_compare_sample_${adapter}.txt")
        add_test(NAME pixel_aot_gather_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_gather_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_gather_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_gather_${adapter}.txt")
        add_test(NAME startup_image_gather_lz_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_gather_lz_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_image_gather_lz_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
        add_test(NAME startup_compute_gather_lz_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_gather_lz_check.py" --dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_gather_lz_${adapter} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_compute_image_store_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_image_store_check.py" --dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_image_store_${adapter} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_compute_image_store_d16_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_image_store_d16_check.py" --dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_image_store_d16_${adapter} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_compute_readfirstlane_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_readfirstlane_check.py" --dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_readfirstlane_${adapter} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_compute_gather_l_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_gather_l_check.py" --dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_compute_gather_l_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME startup_compute_buffer_atomics_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_compute_buffer_atomics_check.py" --dispatch "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(startup_compute_buffer_atomics_${adapter} PROPERTIES TIMEOUT 90 SKIP_RETURN_CODE 77)
        add_test(NAME startup_image_gather_c_lz_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/startup_image_gather_c_lz_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter} $<$<BOOL:${STARTUP_FXC}>:${STARTUP_FXC}>)
        set_tests_properties(startup_image_gather_c_lz_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77)
        add_test(NAME pixel_aot_compare_gather_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_compare_gather_check.py" --draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" "${adapter}")
        set_tests_properties(pixel_aot_compare_gather_${adapter} PROPERTIES TIMEOUT 120 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_compare_gather_${adapter}.txt")
        add_test(NAME pixel_aot_compare_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_compare_check.py" draw "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_compare_${adapter} PROPERTIES TIMEOUT 300 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_compare_${adapter}.txt")
        add_test(NAME bc7_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/bc7_draw_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(bc7_draw_${adapter} PROPERTIES TIMEOUT 60)
        add_test(NAME bc7_mode6_multiblock_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/bc7_mode6_multiblock_check.py" "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(bc7_mode6_multiblock_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    endforeach()
    foreach(adapter IN ITEMS hardware warp)
        add_test(NAME pixel_aot_div_fmas_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" draw-div-fmas "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_div_fmas_${adapter} PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_div_fmas_${adapter}.txt")
        add_test(NAME pixel_aot_bits_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/pixel_aot_check.py" bits "${DXC_EXECUTABLE}"
            "$<TARGET_FILE:offscreen_check>" ${adapter})
        set_tests_properties(pixel_aot_bits_${adapter} PROPERTIES TIMEOUT 180
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_bits_${adapter}.txt")
    endforeach()
    set_tests_properties(pixel_aot_bits_hardware PROPERTIES SKIP_RETURN_CODE 77)
    set_tests_properties(cpu_native_frame_hardware pixel_aot_hardware pixel_aot_buffer_color_hardware
        pixel_aot_three_way_hardware pixel_aot_e64_hardware pixel_aot_blend_scalar_hardware pixel_aot_predicate_rounding_hardware bc7_draw_hardware
        pixel_aot_integer_nc_hardware pixel_aot_align_hardware pixel_aot_vop3_ternary_int_hardware pixel_aot_flat_scratch_hardware
        PROPERTIES SKIP_RETURN_CODE 77)
    set_tests_properties(compute_store_aot_hardware compute_store_aot_guard_read_hardware compute_store_aot_f32_hardware
        compute_store_aot_cvt_u32_f32_hardware compute_store_aot_scratch_base_hardware
        PROPERTIES SKIP_RETURN_CODE 77)
    foreach(adapter IN ITEMS hardware warp)
        # The gfx programs this test translated, for tools/form_coverage.py.
        set_tests_properties(pixel_aot_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_${adapter}.txt")
        set_tests_properties(pixel_aot_predicate_rounding_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_predicate_rounding_${adapter}.txt")
        set_tests_properties(pixel_aot_blend_scalar_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_blend_scalar_${adapter}.txt")
        set_tests_properties(pixel_aot_plain_bitscan_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_plain_bitscan_${adapter}.txt")
        set_tests_properties(pixel_aot_e64_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_e64_${adapter}.txt")
        set_tests_properties(pixel_aot_integer_nc_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_integer_nc_${adapter}.txt")
        set_tests_properties(pixel_aot_align_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_align_${adapter}.txt")
        set_tests_properties(pixel_aot_int16_vop3_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_int16_vop3_${adapter}.txt")
        set_tests_properties(pixel_aot_int16_ternary_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_int16_ternary_${adapter}.txt")
        set_tests_properties(pixel_aot_f16_arith_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_f16_arith_${adapter}.txt")
        set_tests_properties(pixel_aot_f16_round_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_f16_round_${adapter}.txt")
        set_tests_properties(pixel_aot_f16_fmac_ldexp_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_f16_fmac_ldexp_${adapter}.txt")
        set_tests_properties(pixel_aot_f16_cvt_int16_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_f16_cvt_int16_${adapter}.txt")
        set_tests_properties(pixel_aot_f16_to_int16_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_f16_to_int16_${adapter}.txt")
        set_tests_properties(pixel_aot_vop3_ternary_int_${adapter} PROPERTIES
            ENVIRONMENT "FORM_COVERAGE_RECORD=${CMAKE_BINARY_DIR}/form_coverage/pixel_aot_vop3_ternary_int_${adapter}.txt")
    endforeach()
    set_tests_properties(pixel_aot_attribute_hardware pixel_aot_rndne_hardware PROPERTIES SKIP_RETURN_CODE 77)
    set_tests_properties(pixel_aot_dmask_hardware PROPERTIES SKIP_RETURN_CODE 77)
    set_tests_properties(pixel_aot_sample_lod_hardware PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME compressed_scene_metadata COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/scene_records_check.py" "${CMAKE_CURRENT_BINARY_DIR}/DualUav.cso"
        "${CMAKE_CURRENT_BINARY_DIR}/triangle_ps.cso" "$<TARGET_FILE:root_probe>")
    add_test(NAME root_device_controls_warp COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tools/probe_root_devices.py" --warp-only --bin "$<TARGET_FILE_DIR:root_device_probe>")
    add_test(NAME shader_metadata_probe COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/shader_probe_check.py" "$<TARGET_FILE:root_probe>"
        "${CMAKE_CURRENT_BINARY_DIR}/compute_root.cso" "${CMAKE_CURRENT_BINARY_DIR}/compute_tables.cso"
        "${CMAKE_CURRENT_BINARY_DIR}/triangle_vs.cso" "${DXC_BIN_DIR}/dxil.dll")
    set_tests_properties(shader_metadata_probe PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME shader_metadata_controls COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/shader_probe_check.py")
    add_test(NAME shader_rdna_cvt_pk_u8_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/rdna_cvt_pk_u8_cli_check.py")
    set_tests_properties(shader_rdna_cvt_pk_u8_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME shader_metadata_census COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/shader_census_check.py")
    add_test(NAME shader_census_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/shader_census_cli_check.py")
    add_test(NAME shader_profile_audit_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/shader_profile_audit_check.py")
    add_test(NAME shader_profile_audit_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/shader_profile_audit_cli_check.py")
    add_test(NAME shader_metadata_checks COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/probe_roots_cli_check.py")
    # Keep both shader-model profiles in the retarget probe even though the draw fixture uses SM 6.0.
    set(retarget_copy_blocks "${CMAKE_CURRENT_BINARY_DIR}/CopyBlocksSM65.cso")
    add_custom_command(OUTPUT "${retarget_copy_blocks}"
        COMMAND "${DXC_EXECUTABLE}" -T cs_6_5 -E CopyBlocks -Fo "${retarget_copy_blocks}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/buffer_ops.hlsl"
        DEPENDS tests/buffer_ops.hlsl VERBATIM)
    add_custom_target(dxil_retarget_fixture DEPENDS "${retarget_copy_blocks}")
    add_dependencies(root_device_probe dxil_retarget_fixture)
    add_test(NAME dxil_retarget_probe COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/dxil_retarget_check.py" "$<TARGET_FILE:root_probe>"
        "${CMAKE_CURRENT_BINARY_DIR}/compute_root.cso" "${retarget_copy_blocks}"
        "${DXC_BIN_DIR}/dxil.dll" "$<TARGET_FILE:root_device_probe>" "$<TARGET_FILE:offscreen_check>")
    set_tests_properties(dxil_retarget_probe PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME dxil_retarget_probe_hardware COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/dxil_retarget_check.py" "$<TARGET_FILE:root_probe>"
        "${CMAKE_CURRENT_BINARY_DIR}/compute_root.cso" "${retarget_copy_blocks}"
        "${DXC_BIN_DIR}/dxil.dll" "$<TARGET_FILE:root_device_probe>" "$<TARGET_FILE:offscreen_check>" hardware)
    set_tests_properties(dxil_retarget_probe_hardware PROPERTIES TIMEOUT 60 SKIP_RETURN_CODE 77)
    add_test(NAME dxil_retarget_controls COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/dxil_retarget_check.py")
    add_test(NAME xbox_intrinsic_gate_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xbox_intrinsic_gate_check.py")
    add_test(NAME rectlist_topology COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/rectlist_topology_check.py")
    foreach(adapter IN ITEMS warp hardware)
        add_test(NAME rectlist_draw_${adapter} COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/rectlist_topology_check.py"
            --draw "$<TARGET_FILE:rectlist_draw_check>" ${adapter})
        set_tests_properties(rectlist_draw_${adapter} PROPERTIES TIMEOUT 60)
    endforeach()
    set_tests_properties(rectlist_draw_hardware PROPERTIES SKIP_RETURN_CODE 77)
    add_test(NAME conditional_import_paths COMMAND "${INTAKE_PYTHON}" -B "${CMAKE_SOURCE_DIR}/tests/intake/paths_check.py")
    add_test(NAME build_verify_build_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/verify_build_cli_check.py")
    add_library(intake_provider SHARED tests/intake/provider.cpp tests/intake/provider.def)
    add_library(intake_delay SHARED tests/intake/provider.cpp tests/intake/delay.def)
    add_executable(intake_candidate tests/intake/candidate.cpp)
    # Build an import library from a name only. No graphics DLL is linked or executed at build time.
    set(graphics_import "${CMAKE_CURRENT_BINARY_DIR}/intake_graphics.lib")
    add_custom_command(OUTPUT "${graphics_import}"
        COMMAND "${CMAKE_AR}" /nologo /machine:x64 "/def:${CMAKE_CURRENT_SOURCE_DIR}/tests/intake/graphics_import.def"
                "/out:${graphics_import}"
        DEPENDS tests/intake/graphics_import.def VERBATIM)
    target_sources(intake_candidate PRIVATE "${graphics_import}")
    target_link_libraries(intake_candidate PRIVATE intake_provider intake_delay delayimp "${graphics_import}")
    target_link_options(intake_candidate PRIVATE /DELAYLOAD:intake_delay.dll)
    add_test(NAME static_exe_intake COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/intake/check.py" "$<TARGET_FILE:intake_candidate>"
        "$<TARGET_FILE:intake_provider>")
    # intake_forward exports six placeholders. The test rewrites a copy so each export is a forwarder;
    # it reads the images and never loads them.
    add_library(intake_forward SHARED tests/intake/provider.cpp tests/intake/forward.def)
    add_executable(intake_forward_caller tests/intake/forward_caller.cpp)
    target_link_libraries(intake_forward_caller PRIVATE intake_forward)
    add_test(NAME bundled_export_forwarders COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/intake/forwarders_check.py" "$<TARGET_FILE:intake_forward_caller>"
        "$<TARGET_FILE:intake_forward>" "$<TARGET_FILE:intake_provider>")
    add_test(NAME layout_chunk_summary COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/layout_chunks_check.py")
    add_test(NAME textures_paged_resource_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/paged_resource_check.py")
    set_tests_properties(textures_paged_resource_check PROPERTIES TIMEOUT 60)
    add_test(NAME dependency_paths_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/dependency_paths_check.py")
    add_test(NAME pe_dependency_paths_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/dependency_paths_cli_check.py")
    add_test(NAME pe_package_import_closure COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_package_preflight_check.py")
    add_test(NAME pe_package_preflight_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_package_preflight_cli_check.py")
    set_tests_properties(pe_package_preflight_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME pe_inventory_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_inventory_cli_check.py")
    add_test(NAME call_evidence_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/call_evidence_check.py")
    add_test(NAME pe_call_evidence_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/call_evidence_cli_check.py")
    set_tests_properties(pe_call_evidence_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME pe_run_package_invalid_pe COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_run_package_invalid_check.py")
    add_test(NAME pe_run_package_plan_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_run_package_plan_check.py")
    add_test(NAME pe_run_package_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/pe_run_package_cli_check.py")
    add_test(NAME pe_intake_checks COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/intake_exe_check.py")
    add_test(NAME pe_intake_exe_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/intake_exe_cli_check.py")
    set_tests_properties(pe_intake_exe_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME pe_host_commit_preflight COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/host_commit_check.py")
    add_test(NAME xgameruntime_preflight_stub_refused COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xgameruntime_preflight_check.py"
        "$<TARGET_FILE:xgameruntime_preflight_exe>" "$<TARGET_FILE:xmem_shim>"
        "$<TARGET_FILE:d3d12_xs_shim>" "$<TARGET_FILE_DIR:xgameruntime_shim>"
        "$<TARGET_FILE_DIR:xmem_shim>")
    set_tests_properties(xgameruntime_preflight_stub_refused PROPERTIES TIMEOUT 30)
    add_test(NAME pe_run_package_trap_missing COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/trap_missing_check.py" "$<TARGET_FILE:pe_map>"
        "$<TARGET_FILE:trap_missing_exe>" "$<TARGET_FILE:trap_missing_data_exe>")
    set_tests_properties(pe_run_package_trap_missing PROPERTIES TIMEOUT 60)
    add_test(NAME bink_heap_aot_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bink_heap_aot_check.py")
    add_test(NAME runtime_bink_heap_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bink_heap_aot_cli_check.py")
    set_tests_properties(runtime_bink_heap_aot_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME bink_frame_aot_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bink_frame_aot_check.py")
    add_test(NAME runtime_bink_frame_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bink_frame_aot_cli_check.py")
    set_tests_properties(runtime_bink_frame_aot_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME cpu_stdio_exe_aot_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/cpu_stdio_exe_aot_check.py")
    # Documented in the AGENTS platform-independent list but never registered here, so ctest did
    # not run them locally while the CI Python job did.
    add_test(NAME bidi_controls COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bidi_controls_check.py")
    add_test(NAME ci_form_reference_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/form_reference_cli_check.py")
    set_tests_properties(ci_form_reference_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME compat_report COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compat_report_check.py")
    add_test(NAME pe_compat_report_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/compat_report_cli_check.py")
    add_test(NAME form_coverage COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/form_coverage_check.py")
    add_test(NAME gpu_report_format COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/gpu_report_format_check.py")
    add_test(NAME hardware_reports COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/hardware_reports_check.py")
    add_test(NAME tooling_hardware_reports_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/hardware_reports_cli_check.py")
    set_tests_properties(tooling_hardware_reports_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME shader_corpus_report COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/shader_corpus_report_check.py")
    add_test(NAME xgameruntime_table COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/xgameruntime_table_check.py")
    add_test(NAME ffx_create_context_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_create_context_check.py")
    add_test(NAME ffx_device_init_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_device_init_check.py")
    add_test(NAME probe_root_devices_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/probe_root_devices_check.py")
    add_test(NAME ffx_working_set_delta_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_working_set_delta_check.py")
    add_test(NAME ffx_working_set_delta_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/ffx_working_set_delta_cli_check.py")
    set_tests_properties(ffx_working_set_delta_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME bink_descriptors_aot_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bink_descriptors_aot_check.py")
    add_test(NAME tooling_bink_descriptors_aot_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/bink_descriptors_aot_cli_check.py")
    set_tests_properties(tooling_bink_descriptors_aot_cli_check PROPERTIES TIMEOUT 60)
    add_test(NAME range_manifest_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/range_manifest_check.py")
    add_test(NAME pe_resource_inventory_cli_check COMMAND "${INTAKE_PYTHON}" -B
        "${CMAKE_SOURCE_DIR}/tests/resource_inventory_cli_check.py")
else()
    message(WARNING
        "Python-driven tests, including the CPU fixtures, are disabled because "
        "INTAKE_PYTHON was not found at '${INTAKE_PYTHON}'. "
        "Follow the Python setup under First build in README.md, or set INTAKE_PYTHON "
        "to an interpreter with requirements-dev.txt installed. Then rerun CMake.")
endif()

set(vm_raw_srv_header "${CMAKE_CURRENT_BINARY_DIR}/vm_raw_srv_cs.h")
add_custom_command(OUTPUT "${vm_raw_srv_header}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main -Vn vm_raw_srv_cs -Fh "${vm_raw_srv_header}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/vm_raw_srv.hlsl"
    DEPENDS tests/vm_raw_srv.hlsl VERBATIM)
set(vm_raw_uav_header "${CMAKE_CURRENT_BINARY_DIR}/vm_raw_uav_cs.h")
add_custom_command(OUTPUT "${vm_raw_uav_header}"
    COMMAND "${DXC_EXECUTABLE}" -T cs_6_0 -E main -Vn vm_raw_uav_cs -Fh "${vm_raw_uav_header}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/vm_raw_uav.hlsl"
    DEPENDS tests/vm_raw_uav.hlsl VERBATIM)
add_executable(vm_copy_queue_check tests/vm_copy_queue_check.cpp "${vm_raw_srv_header}" "${vm_raw_uav_header}")
target_include_directories(vm_copy_queue_check PRIVATE src "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(vm_copy_queue_check PRIVATE cxx_std_17)
target_link_libraries(vm_copy_queue_check PRIVATE d3d12 dxgi OneCore)
foreach(adapter IN ITEMS warp hardware)
    add_test(NAME vm_copy_queue_${adapter} COMMAND vm_copy_queue_check ${adapter})
    add_test(NAME vm_page_provenance_${adapter} COMMAND vm_copy_queue_check provenance_${adapter})
    add_test(NAME vm_raw_srv_${adapter} COMMAND vm_copy_queue_check raw_srv_${adapter})
    add_test(NAME vm_raw_uav_${adapter} COMMAND vm_copy_queue_check raw_uav_${adapter})
    set_tests_properties(vm_copy_queue_${adapter} vm_page_provenance_${adapter} vm_raw_srv_${adapter}
        vm_raw_uav_${adapter}
        PROPERTIES TIMEOUT 30 SKIP_RETURN_CODE 77)
endforeach()
# Bounds, alignment, 64-bit offsets and view fields of make_raw_buffer_srv (src/raw_buffer_srv.h),
# without a device. The mutated run is the negative control.
add_executable(raw_buffer_srv_check tests/raw_buffer_srv_check.cpp)
target_include_directories(raw_buffer_srv_check PRIVATE src)
target_compile_features(raw_buffer_srv_check PRIVATE cxx_std_17)
add_test(NAME raw_buffer_srv COMMAND raw_buffer_srv_check)
add_test(NAME raw_buffer_srv_first_32_control COMMAND raw_buffer_srv_check --mutate first-32)
set_tests_properties(raw_buffer_srv_first_32_control PROPERTIES WILL_FAIL TRUE)
# Window validation and touching-window boundaries of resolve_raw_uav_store (src/raw_buffer_uav.h),
# without a device. The mutated run is the negative control.
add_executable(raw_buffer_uav_check tests/raw_buffer_uav_check.cpp)
target_include_directories(raw_buffer_uav_check PRIVATE src)
target_compile_features(raw_buffer_uav_check PRIVATE cxx_std_17)
add_test(NAME raw_buffer_uav COMMAND raw_buffer_uav_check)
add_test(NAME raw_buffer_uav_adjacent_control COMMAND raw_buffer_uav_check --mutate adjacent)
set_tests_properties(raw_buffer_uav_adjacent_control PROPERTIES WILL_FAIL TRUE)

if(EXISTS "${INTAKE_PYTHON}")
    add_executable(rcas_coordinate_readback tests/rcas_coordinate_readback/readback.cpp)
    target_link_libraries(rcas_coordinate_readback PRIVATE d3d11 d3dcompiler)
    foreach(control IN ITEMS positive negative)
        add_test(NAME rcas_coordinate_${control}_warp COMMAND "${INTAKE_PYTHON}" -B
            "${CMAKE_SOURCE_DIR}/tests/rcas_coordinate_readback/verify.py" "${CMAKE_SOURCE_DIR}"
            --host $<TARGET_FILE:rcas_coordinate_readback> --backend warp --case ${control})
    endforeach()
endif()

# Per-family registration fragments (see tests/cmake/README.md). Included after every helper and
# target above and before the slow-test costs below, in name order. A new file re-runs configure.
file(GLOB X2W_TEST_FRAGMENTS CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/tests/cmake/*.cmake")
list(SORT X2W_TEST_FRAGMENTS)
foreach(x2w_fragment IN LISTS X2W_TEST_FRAGMENTS)
    include("${x2w_fragment}")
endforeach()

# Start the slowest tests first so the ctest worker pool has no long tail at the end.
# COST only changes scheduling order under `ctest --parallel`; no test, argument or assertion changes.
# Costs are measured seconds (approx.) from the Windows CI ctest log taken when this list was added
# (2026-11-25, main at a6c8d80dc); re-measure when the order looks wrong. Keep the list in descending cost order:
# the loop below stops the configure if it is not. Names absent in a configuration are skipped.
set(X2W_SLOW_TEST_COSTS
    startup_debug 56
    compute_store_aot_heap_view_store_warp 51
    compute_store_aot_descriptor_load_format_warp 51
    cpu_aot_sse_fp_pd 44
    cpu_aot_x87_fprem 41
    compute_store_aot_heap_view_load_warp 37
    startup_run_ps1 37
    pixel_aot_warp 36
    pixel_aot_bits_warp 36
    startup_gamesave_read_publish_locked 33
    pixel_aot_core_vector_warp 33
    pixel_aot_three_way_warp 33
    form_coverage 33
    startup_vertex_fetch_formats_warp 32
    pixel_aot_buffer_color_warp 31
    sampled_coverage_warp 31
    startup_storage_worker_start 30
    cpu_aot_x87_scale 30
    startup_mrt_fxc_warp 30
    startup_heartbeat_commit 30
    pixel_aot_predicate_rounding_warp 30
    startup_mrt_dxc_warp 28
    cpu_aot_xchg 27
    depth_mask_unary_draw_warp 26
    pixel_aot_comparisons_warp 26)
list(LENGTH X2W_SLOW_TEST_COSTS X2W_SLOW_TEST_COSTS_LEN)
math(EXPR X2W_SLOW_TEST_COSTS_LAST "${X2W_SLOW_TEST_COSTS_LEN} - 1")
math(EXPR X2W_SLOW_TEST_COSTS_ODD "${X2W_SLOW_TEST_COSTS_LEN} % 2")
if(X2W_SLOW_TEST_COSTS_ODD)
    message(FATAL_ERROR "X2W_SLOW_TEST_COSTS must hold name/cost pairs")
endif()
set(X2W_SLOW_TEST_PREV_COST "")
foreach(i RANGE 0 ${X2W_SLOW_TEST_COSTS_LAST} 2)
    math(EXPR j "${i} + 1")
    list(GET X2W_SLOW_TEST_COSTS ${i} slow_name)
    list(GET X2W_SLOW_TEST_COSTS ${j} slow_cost)
    if(NOT slow_cost MATCHES "^[0-9]+$")
        message(FATAL_ERROR "X2W_SLOW_TEST_COSTS: cost of ${slow_name} is not an integer: ${slow_cost}")
    endif()
    if(NOT X2W_SLOW_TEST_PREV_COST STREQUAL "" AND slow_cost GREATER X2W_SLOW_TEST_PREV_COST)
        message(FATAL_ERROR "X2W_SLOW_TEST_COSTS must be in descending cost order: ${slow_name} (${slow_cost}) follows ${X2W_SLOW_TEST_PREV_COST}")
    endif()
    set(X2W_SLOW_TEST_PREV_COST ${slow_cost})
    if(TEST ${slow_name})
        set_tests_properties(${slow_name} PROPERTIES COST ${slow_cost})
    endif()
endforeach()
