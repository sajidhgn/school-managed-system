import type { MetadataRoute } from "next";

/**
 * Makes SchoolYar installable ("Add to home screen"), which is what keeps it on a
 * teacher's phone for offline attendance. Next serves this as
 * `/manifest.webmanifest` and links it from every page.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SchoolYar",
    short_name: "SchoolYar",
    description: "School office, attendance, fees and exams in one place.",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    background_color: "#f3f4f6",
    theme_color: "#2447f5",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
