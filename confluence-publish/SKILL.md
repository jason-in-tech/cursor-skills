# Publish Content to Confluence

Create, update, and organize Confluence pages via the project-level Atlassian MCP server.

## Step 0: Discover the MCP Server

The Atlassian server name varies by workspace. Find it by listing `mcps/` in the project metadata folder:

```
ls <project_mcps_folder>/*/SERVER_METADATA.json
```

Look for a folder matching `*atlassian*` (typically `project-0-cruise-atlassian`). Use this as the `server` parameter in all `CallMcpTool` calls. All examples below use `project-0-cruise-atlassian` -- replace with the actual name if different.

## Step 1: Verify Site Authorization and Resolve IDs

### Verify OAuth access to the target site

Before anything else, confirm the target Confluence site is authorized:

```
CallMcpTool(server="project-0-cruise-atlassian", toolName="getAccessibleAtlassianResources", arguments={})
```

This returns a list of authorized sites. Each entry has:
- `id` (UUID) -- the cloudId
- `url` -- the site URL (e.g., `https://gm-sdv.atlassian.net`)
- `name` -- short name (e.g., `gm-sdv`)
- `scopes` -- granted permissions (need `write:page:confluence` for create/update)

**Parse the hostname from the user's Confluence URL** (e.g., `gm-sdv.atlassian.net` from `https://gm-sdv.atlassian.net/wiki/spaces/ADAS/pages/123/Title`) and check if it appears in the accessible resources list. If it does, save the `id` as `cloudId`.

**If the target site is NOT listed**: The user needs to re-authorize. See **Troubleshooting > Re-authentication** below.

**Shortcut**: You can also pass the site hostname directly as `cloudId` to tools (e.g., `"gm-sdv.atlassian.net"` instead of the UUID). The server resolves it automatically. However, if the site isn't authorized, you'll get: `"Cloud id: <uuid> isn't explicitly granted by the user."`

### cloudId

Extract from `getAccessibleAtlassianResources` as described above.

### spaceId (numeric)

The space key (e.g. `"ADAS"`) is **not** the spaceId. The API requires a numeric Long. Two ways to resolve it:

**Option A** -- From a known page in the space:

```
CallMcpTool(server="project-0-cruise-atlassian", toolName="getConfluencePage", arguments={
    "cloudId": "<cloudId>",
    "pageId": "<any known page ID in the space>"
})
```

Extract `spaceId` from the response.

**Option B** -- List all spaces and find by key:

```
CallMcpTool(server="project-0-cruise-atlassian", toolName="getConfluenceSpaces", arguments={
    "cloudId": "<cloudId>",
    "type": "global"
})
```

Find the space by `key` (e.g., `"ADAS"`) and extract its numeric `id`.

### parentId from URL

Parse the numeric ID from the Confluence URL the user provides:
- `https://site.atlassian.net/wiki/spaces/SPACE/folder/1234567` -> `"1234567"`
- `https://site.atlassian.net/wiki/spaces/SPACE/pages/1234567/Title` -> `"1234567"`

## Step 2: Build the Body

Two content formats are supported. **Always use markdown** unless you specifically need ADF-only features (panels, mentions, macros). Markdown bodies are typically 5-10x smaller than equivalent ADF, making them far easier to pass through MCP tool calls.

### Option A: Markdown (always use this)

Pass `contentFormat: "markdown"` and supply the body as a markdown string. The server converts it to Confluence storage format automatically. This handles:

- Headings, bold, italic, code spans
- Bullet and numbered lists
- Tables (pipe syntax)
- Code blocks with language hints
- Links (auto-converted to Smart Links for same-space pages)

**Limitations**: Mermaid diagrams render as code blocks (Confluence doesn't parse mermaid from markdown). Panels, mentions, and other Confluence-specific macros are not available via markdown.

**Updating existing ADF pages**: You can update a page that was originally created in ADF by sending markdown. The server converts it. You do NOT need to read the existing ADF body and modify it -- just rewrite the full page content in markdown. See the anti-pattern warning below.

### Option B: ADF (avoid unless necessary)

Pass `contentFormat: "adf"` (or omit -- it's the default) and supply ADF JSON as the body. Only use this when you specifically need panels, mentions, Smart Links, or other rich Confluence elements that markdown can't express.

**WARNING -- ADF read-modify-write anti-pattern**: Do NOT try to read an existing page's ADF body via `getConfluencePage`, parse the JSON, find specific nodes to modify (e.g. a table row or bullet list), and write it back. This approach is fragile, time-consuming, and produces massive bodies (50KB+) that are difficult to pass through MCP tool calls. Instead, rewrite the full page content in markdown -- it produces a ~5KB body that passes inline and preserves all common formatting.

**HARD LIMIT -- ~46K argument size**: The `CallMcpTool` framework truncates arguments at ~46K characters total (JSON-encoded). An ADF body for a page with tables and images easily exceeds this. Even after aggressive minification (stripping `localId`, `colspan:1`, `rowspan:1`, compact separators), a medium-complexity page hits ~48K. This is NOT fixable by optimizing the ADF -- the limit is in the tool framework.

**Pages with embedded images cannot be safely updated via markdown**: Markdown rewrites lose all `mediaSingle`/`media` attachment references. If the existing page has images uploaded as Confluence attachments, a markdown update will wipe them from the body (attachments remain but are no longer displayed).

**Recommended pattern for image-heavy pages**: Create new content as a **child page** in markdown, leaving the parent page untouched. This preserves all images on the parent while adding structured content underneath. For small edits to the parent (adding a link, removing a bullet), have the user do it manually in the Confluence editor -- it takes 30 seconds vs. risking a page wipe.

Every ADF document is `{"type": "doc", "version": 1, "content": [...]}`. Content is an array of block nodes:

| Block Node | Structure |
|------------|-----------|
| Paragraph | `{"type": "paragraph", "content": [inline nodes...]}` |
| Heading | `{"type": "heading", "attrs": {"level": 1-6}, "content": [inline nodes...]}` |
| Bullet list | `{"type": "bulletList", "content": [listItem nodes...]}` |
| Ordered list | `{"type": "orderedList", "content": [listItem nodes...]}` |
| List item | `{"type": "listItem", "content": [block nodes...]}` |
| Table | `{"type": "table", "attrs": {"isNumberColumnEnabled": false, "layout": "default"}, "content": [tableRow nodes...]}` |
| Table row | `{"type": "tableRow", "content": [tableHeader or tableCell nodes...]}` |
| Table header | `{"type": "tableHeader", "content": [block nodes...]}` |
| Table cell | `{"type": "tableCell", "content": [block nodes...]}` |
| Horizontal rule | `{"type": "rule"}` |
| Code block | `{"type": "codeBlock", "attrs": {"language": "python"}, "content": [text node]}` |

Inline nodes go inside paragraphs/headings:

| Inline Node | Structure |
|-------------|-----------|
| Plain text | `{"type": "text", "text": "hello"}` |
| Bold | `{"type": "text", "text": "hello", "marks": [{"type": "strong"}]}` |
| Code | `{"type": "text", "text": "foo()", "marks": [{"type": "code"}]}` |
| Link | `{"type": "text", "text": "click", "marks": [{"type": "link", "attrs": {"href": "https://..."}}]}` |

Marks can be combined: `"marks": [{"type": "strong"}, {"type": "code"}]`.

For large ADF bodies, write a Python script that builds ADF as nested dicts and serializes to `/tmp/adf_body.json`. Define small helper functions (e.g. `text()`, `para()`, `table_cell()`) to keep the script readable. Always validate the output with `json.loads()` before using it.

### Recommended Header Block

Add metadata at the top of every page:

```
**Authors:** Jason Li with <model>
**Date:** <date>
**AI-assisted:** Yes (Cursor IDE with <model>)
**Branch:** <branch name if applicable>

---
```

For markdown, these are just bold text lines followed by a horizontal rule. For ADF, each line is a paragraph with bold key and plain value, followed by a `rule` node.

## Step 3: Create or Update the Page

### Create

```
CallMcpTool(server="project-0-cruise-atlassian", toolName="createConfluencePage", arguments={
    "cloudId": "<cloudId>",
    "spaceId": "<numeric spaceId>",
    "title": "<page title>",
    "parentId": "<parent folder or page ID as string>",
    "contentFormat": "markdown",
    "body": "<markdown string>"
})
```

### Update

First get the current version number. The response from `getConfluencePage` may be very large (100KB+ for ADF pages). You only need the `version` field -- do NOT try to parse or modify the existing body.

```
CallMcpTool(server="project-0-cruise-atlassian", toolName="getConfluencePage", arguments={
    "cloudId": "<cloudId>",
    "pageId": "<page ID>"
})
```

Then rewrite the full page content in markdown and update with `version` incremented by 1. Even if the existing page was authored in ADF, just send markdown -- the server converts it automatically and all common formatting (tables, bold, code, links, headings) is preserved.

```
CallMcpTool(server="project-0-cruise-atlassian", toolName="updateConfluencePage", arguments={
    "cloudId": "<cloudId>",
    "pageId": "<page ID>",
    "version": <current version number + 1>,
    "title": "<page title>",
    "contentFormat": "markdown",
    "body": "<full page content as markdown>"
})
```

**Tip**: If the page already has substantial content you need to preserve, read it via `getConfluencePage`, mentally note the structure and sections, then reconstruct the full page in markdown with your modifications included. This is far more reliable than trying to surgically edit ADF JSON.

### Organize Hierarchy

1. Create the parent (index) page with `parentId` = target folder ID.
2. Create child pages with `parentId` = new parent page ID.
3. To move an existing page, `updateConfluencePage` with the new `parentId`.

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| "Cloud id: X isn't explicitly granted by the user" | OAuth not authorized for target site | Re-authenticate -- see Troubleshooting below |
| "A page with this title already exists" | Duplicate title in the same space | Use `searchConfluenceUsingCql` to find existing page, then update it instead |
| "Invalid ADF content provided" | Malformed JSON or HTML in `body` | Validate JSON with `json.loads()` before sending. Ensure `{"type": "doc", "version": 1, ...}` wrapper |
| "Provided value {X} for 'spaceId' is not the correct type" | Space key string instead of numeric ID | Resolve numeric spaceId via `getConfluencePage` or `getConfluenceSpaces` (see Step 1) |
| Version conflict (409) | Stale version number on update | Re-fetch page to get current version, increment, retry |
| Page created at space root despite parentId | Used `parentPageId` instead of `parentId` | Use `parentId` -- see Critical Gotchas |
| 403 "Current user not permitted to use Confluence" | API token auth blocked by enterprise SSO | Use OAuth-based server only. Do not use community MCP servers with API tokens for enterprise instances |
| 404 "Cannot find a page with id [X]" when page exists in browser | Page ID is from a different Confluence instance (dev vs prod) | Verify cloudId matches the instance where the page lives. Page IDs are instance-specific |

## Troubleshooting

### Re-authentication (target site not authorized)

Enterprise orgs often have multiple Confluence instances (e.g., `gm-sdv-dev` for dev, `gm-sdv` for production). OAuth is granted per-site. If `getAccessibleAtlassianResources` does not list your target site:

1. Open the project-level `.cursor/mcp.json`
2. Remove the `atlassian` entry, save the file, and wait a few seconds for Cursor to detect the removal
3. Re-add the entry and save:
   ```json
   "atlassian": {
       "url": "https://mcp.atlassian.com/v1/mcp",
       "type": "http"
   }
   ```
4. Cursor will trigger a fresh OAuth flow. In the browser consent screen, **select the target site** (e.g., `gm-sdv` for production)
5. Verify with `getAccessibleAtlassianResources` -- the target site should now appear

### Multi-site environments

- Page IDs, space IDs, and cloud IDs are all instance-specific. A page on `gm-sdv.atlassian.net` has a different ID (or doesn't exist at all) on `gm-sdv-dev.atlassian.net`.
- Always parse the hostname from the user's URL to determine which instance to target.
- If the user's URL points to a different instance than what's authorized, re-auth is needed.

### Token-based auth does not work for enterprise

Enterprise instances with SSO block direct API token access (403 errors). Do not configure community MCP servers like `@aashari/mcp-server-atlassian-confluence` with API tokens -- they will fail. The project-level OAuth server is the only reliable method.

### Deprecated endpoint

The old `https://mcp.atlassian.com/v1/sse` endpoint is deprecated after June 2026. Use `https://mcp.atlassian.com/v1/mcp` instead.

## Critical Gotchas

1. **`parentId`, not `parentPageId`**: The `parentPageId` parameter is silently ignored. Always use `parentId` (string). Works for both folder and page IDs.
2. **`spaceId` must be numeric**: Pass `"440806716"`, not `"ADAS"`.
3. **Verify site authorization first**: Always call `getAccessibleAtlassianResources` before any other API call. Saves time vs. hitting "Cloud id isn't explicitly granted" errors.
4. **Page IDs are instance-specific**: A production page ID won't resolve on a dev instance and vice versa.
5. **~46K argument size limit**: The `CallMcpTool` framework truncates at ~46K total argument characters. ADF for a medium page with tables easily exceeds this even after minification. Markdown stays well under.
6. **Never surgically edit ADF**: Do NOT read the ADF body, modify specific nodes, and write it back. Rewrite full content in markdown instead.
7. **Image-heavy pages: use child pages**: If the existing page has embedded images (mediaSingle/media nodes referencing Confluence attachments), do NOT rewrite in markdown -- this wipes the images from the body. Instead, create new content as a child page in markdown. For small parent page edits (add a link, remove a bullet), have the user edit manually in the Confluence UI.
8. **ADF body wipe risk**: If you accidentally update a page with a truncated or empty body, use Confluence's version history (page menu > Page History > Restore) to recover. Always verify version number before updating.

## Other Useful Tools

| Tool | Purpose |
|------|---------|
| `getConfluencePage` | Read page content, get version number and spaceId |
| `getConfluenceSpaces` | List spaces with numeric IDs (alternative to getConfluencePage for spaceId) |
| `searchConfluenceUsingCql` | Find pages by title, space, or label |
| `searchAtlassian` | Rovo Search across Jira and Confluence (no cloudId needed) |
| `getConfluencePageDescendants` | List child pages of a parent |
| `fetchAtlassian` | Read by ARI: `"ari:cloud:confluence:<cloudId>:page/<pageId>"` |
| `getJiraIssue` | Fetch Jira ticket details: `arguments={"cloudId": "<cloudId>", "issueIdOrKey": "PROJ-123"}` |

## When to Use Google Docs Instead

For **image-heavy reports** (eval results, visualizations, screenshots), consider using
the `google-doc-publish` skill (`~/.cursor/skills/google-doc-publish/SKILL.md`) instead of
Confluence. Google Docs handles inline images natively via base64 embedding, avoids the
~46K payload limit, and produces better-looking tables. Confluence is better for text-heavy
pages, cross-linking within a wiki space, and integration with Jira.