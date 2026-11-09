# Ref codes: tie CRM leads to the ad click (optional)

Most leads arrive in a chat, an email, or a phone call, so the CRM rarely knows which ad brought them. Ref codes
close that gap without cookies or a CRM integration: the site turns the click id (`gclid`) Google adds to ad clicks
into a short code, pre-fills it into the contact message, and sales pastes it into the CRM. `match_ref.py` (run by
the daily scout) finds the click again: campaign, ad group, keyword.

```
code = prefix + SHA1(gclid).hex()[:8].upper()        e.g. AG-1A2B3C4D   (prefix: ref_codes.prefix, default AG-)
```

The gclid itself is never stored in the repo; Google Ads keeps click ids for 90 days and the daily saves only
code -> ad group / keyword / ad per day in `reports/daily/clicks/`.

## Turn it on
1. Auto-tagging on in Google Ads (Admin, Account settings, Auto-tagging), so ad clicks carry `gclid`.
2. Add the snippet below to your site.
3. In `argmax.yaml`: `ref_codes.enabled: true`, `ref_codes.live_from: <the date the snippet went live>`, a CRM
   source, and optionally `crm.columns.ref` (else every cell is searched). Put your own test clicks' codes in
   `ref_codes.test_codes`.
4. Ask whoever logs leads to paste the code from the message into the CRM row.

## Website snippet
Plain JavaScript, no dependencies. It keeps the code for the visit (sessionStorage), then appends it to links and
fills a hidden form field. Adjust the selectors to your site.

```html
<script>
(async function () {
  const PREFIX = "AG-";                      // must match ref_codes.prefix
  const KEY = "argmax_ref";
  const gclid = new URLSearchParams(location.search).get("gclid");
  if (gclid && crypto.subtle) {
    const hash = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(gclid));
    const hex = [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
    sessionStorage.setItem(KEY, PREFIX + hex.slice(0, 8).toUpperCase());
  }
  const code = sessionStorage.getItem(KEY);
  if (!code) return;
  const note = ` (ref ${code})`;

  // Chat or messenger links with a prefilled text, e.g. https://wa.me/123?text=Hi or mailto:?body=Hi
  document.querySelectorAll('a[href*="text="], a[href^="mailto:"]').forEach(a => {
    const url = new URL(a.href);
    const param = url.protocol === "mailto:" ? "body" : "text";
    url.searchParams.set(param, (url.searchParams.get(param) || "") + note);
    a.href = url.toString();
  });

  // Contact forms: a hidden field the CRM import or the sales inbox will show
  document.querySelectorAll("form").forEach(form => {
    let input = form.querySelector('input[name="ref"]');
    if (!input) {
      input = Object.assign(document.createElement("input"), { type: "hidden", name: "ref" });
      form.appendChild(input);
    }
    input.value = code;
  });
})();
</script>
```

Check it: open your site with `?gclid=test123`, then compare the code with
`uv run python -c "import hashlib; print('AG-' + hashlib.sha1(b'test123').hexdigest()[:8].upper())"`.
Add that code to `ref_codes.test_codes`.

## Reading the results
- `matched`: one click has this code; the lead is credited to that campaign / ad group / keyword.
- `ambiguous`: two clicks share the code (rare): reported, never guessed.
- `not_found`: the click is older than the saved window or came from elsewhere.
- Fill rate (`crm.py`, weekly log): leads since `live_from` with a code, divided by all leads since then. Not every
  lead will have one (organic visitors, deleted text, clicks without a gclid). REF_GAP alerts when 14 days of leads
  carry none.
