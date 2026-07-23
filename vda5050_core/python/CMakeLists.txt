# Dual-mode Python bindings:
# - SKBUILD / scikit-build-core: build the pip/wheel package `vda5050`
# - ament (add_subdirectory from parent): install into the ROS site-packages tree

cmake_minimum_required(VERSION 3.15...4.0)

if(SKBUILD)
  project(
    ${SKBUILD_PROJECT_NAME}
    VERSION ${SKBUILD_PROJECT_VERSION}
    LANGUAGES CXX)

  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)

  find_package(pybind11 CONFIG REQUIRED)

  # Build the C++ core as part of the wheel; do not recurse into this
  # directory again and do not install development files into the wheel.
  set(VDA5050_CORE_ENABLE_AMENT OFF CACHE BOOL
    "Enable ROS 2 ament packaging" FORCE)
  set(VDA5050_CORE_INSTALL OFF CACHE BOOL
    "Install standalone vda5050_core development files" FORCE)
  set(BUILD_PYTHON OFF CACHE BOOL "Build Python bindings" FORCE)
  set(BUILD_TESTING OFF CACHE BOOL "Build tests" FORCE)
  set(BUILD_EXAMPLES OFF CACHE BOOL "Build examples" FORCE)
  set(ENABLE_ROS2 OFF CACHE BOOL
    "Enable ROS 2 message support in JSON utilities" FORCE)

  add_subdirectory(
    ${CMAKE_CURRENT_SOURCE_DIR}/..
    ${CMAKE_CURRENT_BINARY_DIR}/vda5050_core)

  pybind11_add_module(_core
    bindings.cpp
    src/rmf_migration.cpp
  )

  target_link_libraries(_core PRIVATE
    pybind11::headers
    vda5050_core::client
    vda5050_core::execution
    vda5050_core::transport
    vda5050_core::types
    vda5050_core::logger
  )

  target_include_directories(_core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
  )

  target_compile_definitions(_core PRIVATE VERSION_INFO=${PROJECT_VERSION})

  install(TARGETS _core DESTINATION vda5050)
  install(TARGETS
    vda5050_client
    vda5050_execution
    vda5050_transport
    vda5050_validation
    vda5050_logger
    vda5050_layout
    LIBRARY DESTINATION vda5050
    RUNTIME DESTINATION vda5050
  )

  if(APPLE)
    set(_runtime_path "@loader_path")
  elseif(UNIX)
    set(_runtime_path "$ORIGIN")
  endif()

  if(DEFINED _runtime_path)
    set_target_properties(
      _core
      vda5050_client
      vda5050_execution
      vda5050_transport
      vda5050_validation
      vda5050_logger
      vda5050_layout
      PROPERTIES
      BUILD_WITH_INSTALL_RPATH ON
      INSTALL_RPATH "${_runtime_path}"
      INSTALL_RPATH_USE_LINK_PATH ON
      BUILD_RPATH "${_runtime_path}"
      MACOSX_RPATH ON
    )
  endif()
else()
  find_package(ament_cmake_python REQUIRED)
  find_package(Python3 COMPONENTS Development REQUIRED)
  find_package(pybind11 REQUIRED)

  pybind11_add_module(_core
    bindings.cpp
    src/rmf_migration.cpp
  )

  target_link_libraries(_core
    PRIVATE
      Python3::Python
      vda5050_core::client
      vda5050_core::execution
      vda5050_core::transport
      vda5050_core::types
      vda5050_core::logger
  )

  target_include_directories(_core
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
  )

  target_compile_definitions(_core PRIVATE VERSION_INFO=0.0.1)

  set(_py_site
    lib/python${Python3_VERSION_MAJOR}.${Python3_VERSION_MINOR}/site-packages)

  install(
    TARGETS _core
    DESTINATION ${_py_site}/vda5050
  )

  install(
    DIRECTORY src/vda5050/
    DESTINATION ${_py_site}/vda5050
    FILES_MATCHING
      PATTERN "*.py"
      PATTERN "*.pyi"
      PATTERN "py.typed"
  )
endif()
