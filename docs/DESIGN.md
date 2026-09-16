# Design decisions

## Event identity and line identity are different

`event_id` identifies a delivery. `line_id` identifies the sale being updated. A replay retains its event ID; a correction has a new event ID and higher revision. Reusing an event ID with different content is an error. A stale revision is audited but cannot overwrite newer data.

## Commit data and offset together

A checkpoint written before sales data could lose events. A checkpoint written after a separately committed sale could duplicate work. A page transaction joins both writes and rolls back when interrupted. Tests inject a failure immediately before the checkpoint.

## Preserve rejected input

Unsupported schemas and invalid fields are quarantined with their raw payload and reason. The page can then advance without repeatedly blocking on the same invalid record. Unexpected conflicts instead roll back the page because they violate identity guarantees.

## Keep analytical SQL outside orchestration

Python ingests and exports. dbt expresses warehouse transformations and validation. PostgreSQL supports a dense calendar and window-function cohort analysis. SQLite remains a portable local demonstration path, with the same ingestion semantics.

## Monetary amounts use integer cents

Line prices are stored as integer cents to avoid binary floating-point monetary accumulation. The UCI importer rounds decimal prices to cents. Warehouse SQL casts multiplication to bigint. Currency conversion, tax and multi-currency accounting are outside scope.

## Tests to discuss in an interview

Explain replay versus correction, demonstrate the failing page and its recovery, show why stale revisions are ignored, and explain how you would add distributed writer coordination. Describe what a rejected schema does to downstream freshness and how an alert could be added.
