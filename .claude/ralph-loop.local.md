---
active: true
iteration: 1
session_id: 9e8b2d52-2742-400e-8bad-285d25e56949
max_iterations: 3
completion_promise: null
started_at: "2026-06-06T07:58:52Z"
---

1) Add interned support from FalkorDB:
- Field(interned=True)

   Map a Python attribute to an interned graph property.

    This is a convenience function that marks a property to use FalkorDB's
    intern() function, which deduplicates by storing a single internal
    copy across the database. This is especially useful for repeated values
    like country names, email domains, tags, or status values.
 
2) Add a Vector datatype for embeddings instead of list[float]

3) Add a GeoLocation datatype with longitude and latitude to resembple the native FalkorDB datatype

4) Automatically use type converters for dateime and Enums (the should not be explicitly defined in the Field)
