# Append the mzPeak link block for DIAPseudoSpectra to the OpenMS tree's TOPP CMakeLists (cluster).
# Idempotent. Paths: fork lib at /scratch/kohlbach/mzpeak-cpp/build, Boost.JSON 1.89 from the ceph env,
# Arrow/Parquet/libzip from contrib (what libOpenMS itself links).
p = "/scratch/kohlbach/OpenMS/src/topp/CMakeLists.txt"; s = open(p).read()
if "SPEXTRACT_WITH_MZPEAK" in s: print("already applied"); raise SystemExit
s += '''
# [speXtract mzpeak] streaming .mzpeak input through the mzPeak C++ library (fork trunk).
if(TARGET DIAPseudoSpectra AND EXISTS /scratch/kohlbach/mzpeak-cpp/build/libmzpeak.a)
  set(_spx_env /ceph/ibmi/abi/oliver/AI/OpenDIAlyzer/opt/env)
  target_compile_definitions(DIAPseudoSpectra PRIVATE SPEXTRACT_WITH_MZPEAK)
  target_compile_features(DIAPseudoSpectra PRIVATE cxx_std_23)
  target_include_directories(DIAPseudoSpectra PRIVATE /scratch/kohlbach/mzpeak-cpp/include /scratch/kohlbach/mzpeak-cpp/boost189inc ${CMAKE_SOURCE_DIR}/src/openms/extern/SQLiteCpp/include ${CMAKE_SOURCE_DIR}/src/openms/extern/SQLiteCpp/sqlite3)
  file(GLOB _spx_numpress /scratch/kohlbach/mzpeak-cpp/build/subprojects/msnumpress/*.a)
  target_link_libraries(DIAPseudoSpectra
    /scratch/kohlbach/mzpeak-cpp/build/libmzpeak.a ${_spx_numpress}
    ${_spx_env}/lib/libboost_json.so
    /scratch/kohlbach/contrib/build/lib/libparquet.a /scratch/kohlbach/contrib/build/lib/libarrow.a
    /scratch/kohlbach/contrib/build/lib/libarrow_bundled_dependencies.a
    /scratch/kohlbach/contrib/build/lib/libzip.so /scratch/kohlbach/contrib/build/lib/libz.so /scratch/kohlbach/contrib/build/lib/libbz2.a -Wl,--exclude-libs,libarrow_bundled_dependencies.a)
  set_target_properties(DIAPseudoSpectra PROPERTIES BUILD_RPATH "${_spx_env}/lib;/scratch/kohlbach/contrib/build/lib")
endif()
'''
open(p, "w").write(s); print("topp CMake block appended")
