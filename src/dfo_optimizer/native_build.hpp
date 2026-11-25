#pragma once

#define DFO_STRINGIFY_INNER(x) #x
#define DFO_STRINGIFY(x) DFO_STRINGIFY_INNER(x)

inline const char* dfo_compiler() noexcept {
#if defined(__clang__)
    return "Clang " __clang_version__;
#elif defined(_MSC_FULL_VER)
    return "MSVC " DFO_STRINGIFY(_MSC_FULL_VER);
#else
    return "GCC " __VERSION__;
#endif
}

inline const char* dfo_flags() noexcept {
    return DFO_NATIVE_FLAGS;
}
