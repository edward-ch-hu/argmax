# Strategy: brand defense

For a business whose own brand name gets searched and competitors (or resellers) bid on it. The loop: own the
brand results cheaply, block brand cannibalisation of non-brand campaigns, and keep brand spend from hiding how the
rest of the account performs.

Config to match: a `brand` topic (your brand name and misspellings as substrings), its own campaign, the brand
ad group mapped in `ad_group_topics`, and `winning_topics` without `brand` (brand traffic converts anyway; it is
not evidence that ads create demand).

## Goal
Keep brand impression share near the top at the lowest CPC, and report non-brand performance separately.

## Success signal
- Counts: non-brand leads and wins (the real job of ads); brand leads are reported but not credited to ads.
- Leading signals only: `conversions.lead_signals`.
- Noise, never judged on: brand clicks, sitelink clicks.

## Evidence rules
- Brand and non-brand are always reported apart; totals that mix them are never used for a decision.
- A non-brand topic follows the B2B or e-commerce evidence floor (whichever template you also run).
- Brand CPC rising 2 weeks in a row is a signal to check competitor activity, not to raise bids blindly.

## Topic spend targets
Brand is held to a small fixed share; the rest follows your main strategy.

| Topic | Target share |
|---|---|
| brand | TBD |
| topic_a | TBD |
| topic_b | TBD |
| other | TBD |

## Phases
### Phase 1: separate brand
- Brand keywords in their own campaign; brand terms as negatives in every non-brand campaign.
- Exit check: under 5% of non-brand spend on brand search terms.

### Phase 2: cheap coverage
- Lower brand bids step by step while impression share stays above 90% (daily stepping can do this if `brand` is
  temporarily in `winning_topics` with a high `rank_lost_band` floor; otherwise the weekly does it).
- Exit check: brand CPC stable for 4 weeks.

### Phase 3: watch
- Weekly: brand impression share, top competitors in auction insights (by hand), and any trademark issues.

## Agent autonomy overrides
- Stricter: never pause the brand campaign without a "yes".
- Stricter: never add a competitor's brand as a keyword.

## Change log
- YYYY-MM-DD: created from strategies/brand-defense.md.
