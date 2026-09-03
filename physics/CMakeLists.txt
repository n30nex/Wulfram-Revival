cmake_minimum_required(VERSION 3.20)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(WulframPhysics LANGUAGES CXX)
    enable_testing()
endif()

add_library(WulframPhysicsCore STATIC
    src/config.cpp
    src/collision_asset.cpp
    src/math.cpp
    src/terrain.cpp
    src/world.cpp
)
add_library(Wulfram::PhysicsCore ALIAS WulframPhysicsCore)

target_include_directories(WulframPhysicsCore
    PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include"
)
target_compile_features(WulframPhysicsCore PUBLIC cxx_std_17)
set_target_properties(WulframPhysicsCore PROPERTIES
    CXX_EXTENSIONS OFF
    POSITION_INDEPENDENT_CODE ON
)

if(MSVC)
    target_compile_options(WulframPhysicsCore PRIVATE /W4 /permissive- /fp:precise)
else()
    target_compile_options(WulframPhysicsCore PRIVATE -Wall -Wextra -Wpedantic -ffp-contract=off)
endif()

set(WULFRAM_PHYSICS_COLLISION_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/../server/wulfram_server/content/collision"
    CACHE PATH "Directory containing user-supplied Wulfram collision assets")

option(WULFRAM_PHYSICS_BUILD_TESTS "Build asset-dependent portable physics tests" OFF)
if(WULFRAM_PHYSICS_BUILD_TESTS)
    add_executable(WulframPhysicsCoreTests tests/core_tests.cpp)
    target_link_libraries(WulframPhysicsCoreTests PRIVATE WulframPhysicsCore)
    target_compile_definitions(WulframPhysicsCoreTests PRIVATE
        WULFRAM_PHYSICS_COLLISION_ROOT="${WULFRAM_PHYSICS_COLLISION_ROOT}"
    )
    if(MSVC)
        target_compile_options(WulframPhysicsCoreTests PRIVATE /W4 /permissive- /fp:precise)
    else()
        target_compile_options(WulframPhysicsCoreTests PRIVATE -Wall -Wextra -Wpedantic -ffp-contract=off)
    endif()
    add_test(NAME WulframPhysicsCoreTests COMMAND WulframPhysicsCoreTests)
endif()

option(WULFRAM_PHYSICS_BUILD_C_API "Build the coarse native sandbox C API" ON)
if(WULFRAM_PHYSICS_BUILD_C_API)
    add_library(WulframPhysicsC SHARED
        c_api/src/c_api.cpp
        c_api/include/wulfram/physics/c_api.h
    )
    target_include_directories(WulframPhysicsC PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/c_api/include"
    )
    target_link_libraries(WulframPhysicsC PRIVATE WulframPhysicsCore)
    target_compile_definitions(WulframPhysicsC PRIVATE WULFRAM_PHYSICS_C_EXPORTS)
    set_target_properties(WulframPhysicsC PROPERTIES CXX_EXTENSIONS OFF)
    if(MSVC)
        target_compile_options(WulframPhysicsC PRIVATE /W4 /permissive- /fp:precise /EHsc)
    else()
        target_compile_options(WulframPhysicsC PRIVATE -Wall -Wextra -Wpedantic -ffp-contract=off)
    endif()

    if(WULFRAM_PHYSICS_BUILD_TESTS)
        add_executable(WulframPhysicsCApiTests tests/c_api_tests.cpp)
        target_link_libraries(WulframPhysicsCApiTests PRIVATE WulframPhysicsC)
        target_compile_definitions(WulframPhysicsCApiTests PRIVATE
            WULFRAM_PHYSICS_COLLISION_ROOT="${WULFRAM_PHYSICS_COLLISION_ROOT}"
        )
        if(MSVC)
            target_compile_options(WulframPhysicsCApiTests PRIVATE /W4 /permissive- /fp:precise)
        else()
            target_compile_options(WulframPhysicsCApiTests PRIVATE
                -Wall -Wextra -Wpedantic -ffp-contract=off)
        endif()
        add_test(NAME WulframPhysicsCApiTests COMMAND WulframPhysicsCApiTests)
    endif()
endif()

option(WULFRAM_PHYSICS_BUILD_PYTHON "Build the coarse native Python binding when a matching interpreter is available" ON)
if(WULFRAM_PHYSICS_BUILD_PYTHON AND CMAKE_SIZEOF_VOID_P EQUAL 8)
    find_package(Python3 COMPONENTS Interpreter Development.Module QUIET)
    if(Python3_FOUND)
        Python3_add_library(WulframPhysicsPython MODULE WITH_SOABI
            bindings/python/module.cpp
        )
        target_link_libraries(WulframPhysicsPython PRIVATE WulframPhysicsCore)
        set_target_properties(WulframPhysicsPython PROPERTIES
            CXX_EXTENSIONS OFF
            OUTPUT_NAME "_wulfram_physics"
        )
        if(MSVC)
            target_compile_options(WulframPhysicsPython PRIVATE /W4 /permissive- /fp:precise /EHsc)
        else()
            target_compile_options(WulframPhysicsPython PRIVATE
                -Wall -Wextra -Wpedantic -ffp-contract=off)
        endif()

        if(WULFRAM_PHYSICS_BUILD_TESTS)
            add_test(
                NAME WulframPhysicsPythonTests
                COMMAND "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tests/python_binding_tests.py"
                    "$<TARGET_FILE:WulframPhysicsPython>"
                    "${WULFRAM_PHYSICS_COLLISION_ROOT}"
            )
        endif()
    else()
        message(STATUS "WulframPhysicsPython skipped: matching 64-bit Python development files were not found")
    endif()
endif()
