export default function TablesLayout({ children }: { children: React.ReactNode }) {
  // Tables are a standalone section, like the map: full-bleed, no
  // sidebar / topbar chrome. The tab bar inside each page provides
  // its own navigation. Keep this layout thin — no Providers re-wrap
  // here because the root layout already mounts HeroUIProvider +
  // QueryClientProvider once for the whole app.
  return <>{children}</>;
}
