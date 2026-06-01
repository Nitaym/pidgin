-- Phase 1B: operator hire brief on ai_employees (see specs/SCHEMA_SPEC.md §7.1)

PRAGMA foreign_keys = ON;

ALTER TABLE ai_employees ADD COLUMN hire_customization_json TEXT;
