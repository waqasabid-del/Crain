import { API_BASE_URL } from "../env.js";

/**
 * Where "Connect GitHub" sends the reader.
 *
 * A GitHub App is installed on GitHub, not here: the reader chooses the
 * organisation and the repositories on GitHub's own consent screen, and GitHub
 * then redirects back with an `installation_id`. There is no way to do this
 * from inside the product, and pretending otherwise — a form asking for a
 * personal access token — is how a product ends up holding a credential with
 * far wider scope than it needs.
 *
 * The app's public slug is build-time configuration rather than a constant,
 * because it differs between the development app and the production one. A
 * missing value produces a link to GitHub's app directory rather than a broken
 * URL: the reader can still find the app by name, which is a worse experience
 * than a direct link and a far better one than a 404.
 */
export function githubInstallUrl(): string {
  const slug = process.env.NEXT_PUBLIC_GITHUB_APP_SLUG;
  if (slug === undefined || slug === "") return "https://github.com/apps";

  // `state` carries nothing. The callback is authenticated by the reader's own
  // session on return, so there is no need to round-trip an identifier through
  // GitHub — and a workspace id in a URL a third party redirects to is a value
  // an attacker can substitute.
  return `https://github.com/apps/${encodeURIComponent(slug)}/installations/new`;
}

/**
 * The API origin, for the one place the app links to a server-rendered page.
 *
 * Exported from here rather than imported from `env.js` at the call site so
 * that the reason is written down once: everything else in this app talks to
 * the API through the typed client, and a raw URL is a deliberate exception.
 */
export { API_BASE_URL };
