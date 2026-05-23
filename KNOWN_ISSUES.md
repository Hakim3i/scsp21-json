# Known issues (scsp21-json)

## Animation parsing

- **Header count vs stream:** a handful of files declare more animations in the
  header than the stream contains (e.g. `tywin.scsp` 18 parsed / 20 declared).
  These appear to be asset-side gaps, not padding the resync logic can bridge.
- **Trailing padding:** some combat models leave 10–110 bytes after the last
  animation before `8 + data_size` (e.g. `achates.scsp` leaves 30 bytes).
- **Pet / odd attachments:** some pet SCSP files use attachment type IDs the
  skeleton reader does not yet map (`704`, `736`, …); conversion fails before
  the animation stage.

## Visual / data mismatches

See project notes and e7herder comparisons for mesh/FFD cases that are data
issues rather than converter bugs.
