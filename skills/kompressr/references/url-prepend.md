# Optimize existing website files with URL prepend

Use this route when supported public files already live on your website/origin and you want to keep that hosting. It does not require an SDK or file upload.

## First working asset

1. Create a website project and verify the source domain in the dashboard.
2. Pick one public asset that loads from its original HTTPS URL. Confirm the file type and limits are included in your plan.
3. Prefix the full original URL:

```text
Original:
https://www.example.com/images/hero.jpg

Kompressr:
https://cdn.kompressr.com/YOUR_PROJECT_ID/https://www.example.com/images/hero.jpg
```

Replace `YOUR_PROJECT_ID` with the project's UUID and the example origin with the verified origin hosting the file. Do not include an API key. **Do not percent-encode the whole original URL.** Keep the embedded `https://` and preserve existing URL encoding/query values.

4. Use the prefixed URL in the asset's actual reference, then inspect the file and page. The first request may deliver the origin while processing runs; repeat after processing to inspect the optimized result.

```html
<img
  src="https://cdn.kompressr.com/YOUR_PROJECT_ID/https://www.example.com/images/hero.jpg"
  alt="A description of the image"
  width="1200"
  height="800"
>
```

This changes an image URL, not the site's page URL or DNS routing.

## Construct URLs carefully

- Resolve relative asset paths against the correct public origin before prefixing. `/images/hero.jpg` alone is not a full source URL.
- Preserve source query parameters such as `?v=2` or `?format=pjpg`; they can select different origin content. Kompressr controls use the `kmp-` namespace.
- Use `&` to append a control when the source already has a query. Escape `&` as `&amp;` in literal HTML attributes; runtime URL values still use `&`.
- Do not prepend URLs already delivered by Kompressr, private signed URLs, `data:`/`blob:` values, page navigations or API requests.
- Keep sensitive origin tokens out of public pages. Sources requiring cookies, login or private-network reachability are not ordinary public URL-prepend sources.
- Prefer stable public asset paths. Preserve a fragment if the browser needs it, such as an SVG fragment; fragments are client-side and are not sent in HTTP requests.

For fixed integrations, a configured public prefix plus an application-controlled asset path is often sufficient. For dynamic user-supplied URLs, validate scheme, source host and allowed asset use before constructing a URL.

## Controls and variants

| Control | Use | Limit |
| --- | --- | --- |
| Default image URL | Browser-aware image format delivery | Formats and responsive variants depend on plan/generated output |
| `kmp-format=webp` or `kmp-format=avif` | Explicit image format preference | AVIF must be available; inspect the response |
| `kmp-format=original` | Original image representation where supported | Useful for comparison; does not prove another request was optimized |
| `kmp-size=max` | Plan's maximum supported image size | Check plan support; not an arbitrary width/height transform |
| `kmp-quality=480p`, `720p`, `1080p`, `4k` | Video output quality | Resolution/duration/processing limits apply; 4K needs an eligible plan |

Example preserving a source version:

```text
https://cdn.kompressr.com/YOUR_PROJECT_ID/https://www.example.com/hero.jpg?v=2&kmp-format=webp
```

Do not copy another service's `w=`, `h=`, crop or fit syntax and assume it is a Kompressr feature. Non-Kompressr query keys can belong to the origin. For uploaded files use returned URLs rather than reconstructing paths. Request a private variant through the signing API; preserve signed links unchanged.

## Integrate at the correct layer

| Application | Place to inspect/change |
| --- | --- |
| HTML or server templates | Selected `src`, `srcset`, stylesheet/script and CSS `url()` references |
| Next.js | `assetPrefix` for `/_next/static`; public files and `next/image` need separate treatment |
| Vite/static bundles | Asset-base/public-path configuration and emitted assets; check lazy chunks and CSS-relative resources |
| Django/Rails and other server frameworks | Asset URL helpers, static asset configuration or templates |
| CMS | A documented URL/configuration integration; confirm plugin availability rather than inventing a package |

Read [framework notes](frameworks.md) and the relevant [integration guide](https://kompressr.com/integrations) before changing a build-wide prefix. Script/style transformation can invalidate Subresource Integrity. Address the mismatch explicitly; do not silently remove security controls. Module scripts and fonts need appropriate CORS behavior. Preserve the existing Content Security Policy and add only required delivery origins.

## Roll out and recover

Start with one asset or page, then expand to the chosen asset family. Check dimensions/quality, fonts, PDF/video playback and script behavior as relevant. Test a production build preview; development paths may differ.

Keep original URLs/configuration available for rollback. A prefix rollback changes future requests; browser caches can retain earlier responses. Use new source filenames or version query parameters for changed content that needs a fresh URL. Changing origin bytes does not instantly invalidate all cached copies.

Deleting a URL-prepend asset removes Kompressr's generated files asynchronously, not the origin. After stored/cached copies clear, a later request can fetch the origin and regenerate an asset. For permanent withdrawal, control the source and application references as well.

Official details: [technical documentation](https://kompressr.com/docs), [existing-site workflow](https://kompressr.com/solutions/file-optimization-cdn), [plan support](https://kompressr.com/pricing#file-support).
