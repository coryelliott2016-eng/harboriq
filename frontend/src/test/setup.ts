import "@testing-library/jest-dom/vitest";
// Phase 12: offline queue / job cache tests exercise real IndexedDB code
// paths (src/lib/offlineDb.ts) -- jsdom has no IndexedDB implementation, so
// fake-indexeddb provides an in-memory one globally for every test file.
import "fake-indexeddb/auto";

// Phase 14: recharts' <ResponsiveContainer> measures its DOM node via
// ResizeObserver, which jsdom does not implement. Without a stub, any test
// that renders a report chart throws "ResizeObserver is not defined".
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof MockResizeObserver }).ResizeObserver =
  MockResizeObserver;
