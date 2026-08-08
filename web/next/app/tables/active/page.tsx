import { redirect } from 'next/navigation';

// The four per-tab subroutes used to be standalone pages under
// (dashboard)/tables. We have since moved everything into a single
// /tables page with ?tab=… as the source of truth, so these URLs
// now redirect. Keeping the route files around (instead of returning
// 404) preserves bookmarks, external links and any tests that point
// at the old addresses.
export default function TablesActiveRedirect() {
  redirect('/tables?tab=active');
}
