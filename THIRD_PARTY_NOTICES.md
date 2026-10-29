# Third-party notices and exclusions

These notices identify upstream dependency scope. They do not grant or replace any licence. Any accompanying first-party `LICENSE` applies only to confirmed first-party expression, not to the components or assets listed here. `EXCLUSIONS.json` records their individual hashes and upstream notice locations.

## Dependency distributions are not included

This source release includes none of the 31 pinned dependency wheels, SDK distributions, wheel-bundled components, game assets, Agents fixtures, CPython, pip or platform software. The notebook obtains its runtime dependencies from the official competition input. It embeds project source/configuration, not the third-party wheels or games.

The labels below summarize the pinned wheels' own metadata and licence paths. Short labels are not a substitute for exact upstream texts or bundled-component notices. Classifier-only and dual/project declarations are preserved as such rather than converted into a stronger licence conclusion.

| Dependency | Version | Recorded licence indication | Upstream notice storage |
| --- | --- | --- | --- |
| annotated-types | 0.7.0 | MIT (wheel classifier) | `annotated_types-0.7.0.dist-info/licenses/LICENSE` |
| arc-agi | 0.9.8 | MIT (full text in METADATA) | full MIT notice in package `.dist-info/METADATA` |
| arcengine | 0.9.3 | MIT (full text in METADATA) | full MIT notice in package `.dist-info/METADATA` |
| blinker | 1.9.0 | MIT (wheel classifier) | `blinker-1.9.0.dist-info/LICENSE.txt` |
| certifi | 2026.2.25 | MPL-2.0 | `certifi-2026.2.25.dist-info/licenses/LICENSE` |
| charset-normalizer | 3.4.7 | MIT | `charset_normalizer-3.4.7.dist-info/licenses/LICENSE` |
| click | 8.3.2 | BSD-3-Clause | `click-8.3.2.dist-info/licenses/LICENSE.txt` |
| contourpy | 1.3.3 | BSD-3-Clause (wheel text) | `contourpy-1.3.3.dist-info/LICENSE` |
| cycler | 0.12.1 | BSD-style; see upstream text | `cycler-0.12.1.dist-info/LICENSE` |
| Flask | 3.1.3 | BSD-3-Clause | `flask-3.1.3.dist-info/licenses/LICENSE.txt` |
| fonttools | 4.62.1 | MIT plus LICENSE.external | `fonttools-4.62.1.dist-info/licenses/LICENSE`; `fonttools-4.62.1.dist-info/licenses/LICENSE.external` |
| idna | 3.11 | BSD-3-Clause | `idna-3.11.dist-info/licenses/LICENSE.md` |
| itsdangerous | 2.2.0 | BSD-style; see upstream text | `itsdangerous-2.2.0.dist-info/LICENSE.txt` |
| Jinja2 | 3.1.6 | BSD-style; see upstream text | `jinja2-3.1.6.dist-info/licenses/LICENSE.txt` |
| kiwisolver | 1.5.0 | Modified BSD (wheel text) | `kiwisolver-1.5.0.dist-info/licenses/LICENSE` |
| MarkupSafe | 3.0.3 | BSD-3-Clause | `markupsafe-3.0.3.dist-info/licenses/LICENSE.txt` |
| matplotlib | 3.10.8 | project licence; PSF classifier; see upstream text | `matplotlib-3.10.8.dist-info/LICENSE` |
| numpy | 2.4.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | 17 licence files; paths recorded in EXCLUSIONS.json |
| packaging | 26.1 | Apache-2.0 OR BSD-2-Clause | 3 licence files; paths recorded in EXCLUSIONS.json |
| pillow | 12.2.0 | MIT-CMU | `pillow-12.2.0.dist-info/licenses/LICENSE` |
| pydantic | 2.13.2 | MIT | `pydantic-2.13.2.dist-info/licenses/LICENSE` |
| pydantic_core | 2.46.2 | MIT | `pydantic_core-2.46.2.dist-info/licenses/LICENSE` |
| pyparsing | 3.3.2 | MIT | `pyparsing-3.3.2.dist-info/licenses/LICENSE` |
| python-dateutil | 2.9.0.post0 | dual licence; see upstream text | `python_dateutil-2.9.0.post0.dist-info/LICENSE` |
| python-dotenv | 1.2.2 | BSD-3-Clause | `python_dotenv-1.2.2.dist-info/licenses/LICENSE` |
| requests | 2.33.1 | Apache-2.0 | `requests-2.33.1.dist-info/licenses/LICENSE`; `requests-2.33.1.dist-info/licenses/NOTICE` |
| six | 1.17.0 | MIT | `six-1.17.0.dist-info/LICENSE` |
| typing_extensions | 4.15.0 | PSF-2.0 | `typing_extensions-4.15.0.dist-info/licenses/LICENSE` |
| typing-inspection | 0.4.2 | MIT | `typing_inspection-0.4.2.dist-info/licenses/LICENSE` |
| urllib3 | 2.6.3 | MIT | `urllib3-2.6.3.dist-info/licenses/LICENSE.txt` |
| Werkzeug | 3.1.8 | BSD-3-Clause | `werkzeug-3.1.8.dist-info/licenses/LICENSE.txt` |

The `arc-agi` and `arcengine` wheel METADATA retains the complete upstream MIT grant, copyright, notice condition and disclaimer despite having no separate licence-file member. Their distributions and the SDK source extracts are not part of this release.

## Conditions remain with their upstream material

If MIT-covered software is redistributed, retain its copyright and permission notice in copies or substantial portions. [MIT text](https://opensource.org/license/mit).

For BSD-3-Clause redistribution, retain the copyright, conditions and disclaimer, reproduce them with binary distributions, and do not imply endorsement. [BSD-3-Clause text](https://opensource.org/license/bsd-3-clause).

For Apache-2.0 works or derivatives redistributed separately, provide the licence, mark modifications, retain applicable source notices and carry applicable upstream NOTICE attribution. Separable interface linking is distinguished from derivative works in section 1. [Apache-2.0 sections 1 and 4](https://www.apache.org/licenses/LICENSE-2.0).

For MPL-2.0-covered material redistributed separately, retain notices, keep covered source under MPL and provide required source-availability information with executable distributions. Larger-work licensing does not replace the covered files' conditions. [MPL-2.0 sections 3.1-3.4](https://www.mozilla.org/en-US/MPL/2.0/).

Other recorded licences and bundled components retain their exact terms. In particular, NumPy, Matplotlib, Pillow, fonttools external components and dual-licensed packages should not be treated as uniformly plain MIT. A later bundle containing these distributions needs their complete upstream texts and applicable component notices; they are omitted here.

## Public games and protocol reference

The 51 omitted public-development files include the supplied Apache-2.0 `environment_files/LICENSE`, game Python sources and metadata. The supplied licence's hash is `3ddf9be5c28fe27dad143a5dc76eea25222ad1dd68934a047064e56ed2fa40c5`. Their bytes are not distributed here.

The gateway protocol reference is the [official Stochastic Goose notebook](https://www.kaggle.com/code/inversion/arc3-sample-submission-stochastic-goose), observed version 306264530, with its displayed Apache-2.0 licence. The reference documents the gateway API and orchestration contract. It is not included in this release, and its licence is not replaced by any first-party grant. Applicable upstream notices must remain with any upstream portions actually redistributed.

No endorsement by ARC Prize Foundation, Kaggle or dependency authors is asserted. Upstream identifiers, names, citations and licence facts are not claimed as new first-party property.
