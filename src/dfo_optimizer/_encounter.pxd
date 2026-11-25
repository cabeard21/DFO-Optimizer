"""Native encounter adapters share one checked input compiler."""
cdef extern from "encounter_kernel.hpp" namespace "dfo_enc":
    cdef cppclass PackedEncounter "dfo_enc::Encounter":
        pass

cdef PackedEncounter freeze_scene_abi(dict raw) except *
