# Gallery

**Demo video:** [hearthline-demo.mp4](hearthline-demo.mp4), 2:55, 1280 x 720, narrated and captioned, recorded on the
hosted demo with real sandbox payments. Upload it to YouTube (public or unlisted) for Devpost. Re-record it with
`uv run --with playwright --with imageio-ffmpeg --with edge-tts python ../e2e/video_tour.py` from `backend/` after a
demo reset.

Screenshots of the hosted demo for the Devpost gallery, 3:2 at 2880 x 1920. Retake them with
`uv run --with playwright python ../e2e/gallery.py` from `backend/` (`ONLY=dispatch,giving` retakes some).

| Image | Caption |
|---|---|
| [01-landing.jpg](01-landing.jpg) | The first page is a guide for judges: the problem in sourced numbers, and every feature one click away. |
| [02-recovery-navigator.jpg](02-recovery-navigator.jpg) | Elena's next steps with real dates, worked out in code, and the recovery navigator explaining them in Spanish. |
| [03-inventory-pivot-chart.jpg](03-inventory-pivot-chart.jpg) | AG Grid pivot mode and a pivot chart: what each room held, by kind of item, from photos taken before the fire. |
| [04-registry-paypal.jpg](04-registry-paypal.jpg) | A family's Rebuild Registry: give for a specific need with PayPal, Venmo or Pay Later, in six currencies. |
| [05-command-center-ask-the-grid.jpg](05-command-center-ask-the-grid.jpg) | The Command Center: AG Grid's server-side row model over 2,005 households. "Ask the grid" turned a question into these filters. |
| [06-crew-dispatch-scheduler-pro.jpg](06-crew-dispatch-scheduler-pro.jpg) | The dispatch agent's plan as dashed proposals on Bryntum Scheduler Pro. Code fits every visit and drive; nothing moves until a person accepts. |
| [07-rebuild-what-if-gantt.jpg](07-rebuild-what-if-gantt.jpg) | What if framing runs two weeks late? Bryntum Gantt's scheduling engine moves every step after it; the family sees the new move-in day and which payments move. |
| [08-scam-review-sentinel.jpg](08-scam-review-sentinel.jpg) | A copycat fundraiser. Sentinel flags copied photos, an address outside the fire and a shared PayPal account; it never decides, two reviewers do. |
| [09-giving-mandate.jpg](09-giving-mandate.jpg) | Giving mandates: a donor saves their PayPal account once and sets limits; the giving agent gives to verified needs and explains each gift. |
| [10-price-watch-chart.jpg](10-price-watch-chart.jpg) | Price Watch: an AG Grid integrated chart of the biggest price rises since before the disaster, red over the legal limit. |
| [11-architecture.jpg](11-architecture.jpg) | How it fits together: an AI agent proposes, rules in code check it, a person approves, PayPal moves the money, and the ledger records it. |

The project thumbnail is [thumbnail.png](thumbnail.png) (1500 x 1000, 3:2), made from `thumbnail.html` and two of
the screenshots above.
