import { vi } from "vitest";

/**
 * The App Router's state, for tests. `next/navigation` exports no `MemoryRouter`
 * equivalent, so the module is mocked.
 *
 * **Registered in `vitest.setup.ts`, not here and not in a test file**: `vi.mock`
 * is hoisted to the file that calls it, so a mock declared in a shared helper
 * applies only sometimes, depending on import order.
 */
export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

let currentPath = "/";
let currentSearch = "";

export function setRoute(path: string, search = ""): void {
  currentPath = path;
  currentSearch = search;
  router.push.mockClear();
  router.replace.mockClear();
}

export const navigationMock = {
  useRouter: () => router,
  usePathname: () => currentPath,
  useSearchParams: () => new URLSearchParams(currentSearch),
  useParams: () => ({}),
  notFound: () => {
    throw new Error("notFound() was called");
  },
  redirect: (url: string) => {
    router.replace(url);
  },
};
