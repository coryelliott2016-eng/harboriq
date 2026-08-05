import "@testing-library/jest-dom/vitest";
// Phase 12: offline queue / job cache tests exercise real IndexedDB code
// paths (src/lib/offlineDb.ts) -- jsdom has no IndexedDB implementation, so
// fake-indexeddb provides an in-memory one globally for every test file.
import "fake-indexeddb/auto";
