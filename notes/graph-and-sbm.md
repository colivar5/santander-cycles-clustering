# Graph and SBM

**Status: approved 2026-11-22.** G1–G8 as proposed, G7 with the extra fixed-K fit, G9 (a). Written before `src/graph.py` or `src/sbm.py` exists and before any look at the graph: no edge count, degree, weight distribution or partition has been computed. Once approved, the choices are fixed for the graph and SBM runs; a change after that goes in a new commit that says why.

**Amendment, approved 2026-11-24 (D25), written after looking at the main SBM run.** See G6. G6's main partition and the level at which G3 and G8 compare fits are replaced.

What is known so far, all from the clean stage (`output/runs/clean/20261122T175304Z/` in the cloud, `20261122T175858Z` on your Mac, same SHA-256): 9,067,251 trips kept, 805 station ids after R9, 305,702 round trips (3.37% of trips).

How the stages run (decision D23, approved): `src/graph.py` runs in env_311 and writes the edge list; `src/sbm.py` runs on Homebrew's Python 3.15 (graph-tool 3.9, numpy 2.5.5) and uses nothing else outside the standard library.

## What the brief asks

Brief §4.1: « le poids w_ij est le nombre de trajets observés de i vers j en 2025. »

Brief §4.2: *to add: the wording is not in this session.*

## Choices

Each choice says what it does, then **Proposed** and **Other options**. Items marked **You decide** have no proposal from me.

### G1. Nodes

**Decided: as proposed.**

**Proposed:** every station id in `trips_clean` after R9 and R10: 805 nodes. Every one has at least one trip, so none is isolated.

**Other options:** drop stations with fewer than N trips in 2025. I have no source for N. The degree-corrected SBM (G4) is meant to handle stations with few trips, which is a reason not to need a threshold.

### G2. Edges and weights

Directed: i → j and j → i are different edges. w_ij is the number of trips in `trips_clean` that start at i and end at j, using the merged ids, as §4.1 says. Fixed by the brief; no choice.

### G3. Self-loops (round trips)

**Decided: (b), as proposed.**

The edge list keeps w_ii for every station, so the round trips stay in the data whatever is chosen here.

**Proposed:** (b) the main SBM fit leaves self-loops out, and one extra fit with self-loops is run and compared with it (G8 says how).

Why: a self-loop says nothing about which stations a station is linked to, and round trips are already available to the station profiles (§3). But they are 3.37% of trips and may be concentrated at a few stations (not verified), so the extra fit shows whether leaving them out changes the blocks.

**Other options:**
- (a) Keep self-loops in the main fit. In an SBM they count as edges inside the station's own block and add to its degree.
- (c) Leave them out, with no extra fit.

### G4. Which SBM

**Decided: as proposed.**

**Proposed:** fit both the standard SBM (Holland, Laskey & Leinhardt, 1983) and the degree-corrected SBM (Karrer & Newman, 2011). Keep the one with the **lower description length** as the main result and report both values.

Why: without degree correction, an SBM tends to put stations in blocks by how busy they are rather than by where their trips go (Karrer & Newman, 2011). The description length is graph-tool's own criterion for choosing between models fitted to the same graph (Peixoto, 2014, 2017). Fixing the rule now means the choice is not made by looking at the blocks.

**Other options:**
- (a) Degree-corrected only.
- (b) Standard only.

### G5. How the trip counts enter the model

**Decided: (a), as proposed.**

**Proposed:** (a) each trip is one edge. The graph is a multigraph in which i → j has w_ij parallel edges. In graph-tool this means the edge list with w_ij passed as the edge multiplicity (`eweight`), not 9 million separate edges. This models the count itself, which is what §4.1's weight is.

**Other options:**
- (b) A weighted SBM (Peixoto, 2018): an edge where w_ij ≥ 1, with w_ij as a separate value modelled by a chosen distribution (for example geometric or Poisson). This models "which pairs are connected" and "how many trips" separately, and needs a choice of distribution.
- (c) Binary: an edge where w_ij ≥ 1, and the counts are ignored. Probably most pairs with any trip have very few (not verified), so this would weight a single trip the same as thousands.

### G6. Flat or nested

**Decided: nested, as proposed.**

**Amendment (D25), after looking.** What was seen (run `output/runs/sbm/20261123T194317Z/`, your Mac): in every fit, level 0 has 801–803 blocks for 805 stations, so the lowest level is almost one block per station. The kept standard fit (seed 51) has 803, 209, 46, 13, 5, 4 and 3 blocks at levels 0–6. Across the 30 fits, level 1 has 173–217 blocks, level 2 36–52, level 3 10–18. At level 0 the NMI of every fit against the kept fit is 0.9994–1.0, and the self-loop comparison gives NMI 0.9996 and ARI 0.333, which describe only the few station pairs sharing a block.

Decided:
- The SBM partition used to describe the network's structure (§4.2) is **level 2 of the kept fit** of the model G4 keeps.
- The spread across seeds (G8) and the self-loop comparison (G3) are measured at **every level**, not only the lowest: NMI and ARI between partitions at the same level number. Levels are numbered as written in `blocks.csv`, after leaving out levels identical to the one below.
- The §4.3 comparison still uses the fixed-K fit (G7).
- No refit.

**Proposed:** nested (Peixoto, 2014). The model fits a hierarchy of blocks: stations into blocks, blocks into bigger blocks, and so on. The lowest level is the main partition. Higher levels give coarser partitions that can be shown without choosing K by hand.

**Other options:**
- (a) Flat SBM, K chosen by minimum description length.

### G7. Number of blocks K

**Decided: K by minimum description length for the main result, as proposed; plus the extra fixed-K fit.** The extra fit is a flat SBM with exactly K blocks, K being the number of clusters chosen in §3, using the model G4 keeps and the G8 procedure. It is used only for the §4.3 comparison. It runs after §3's K is decided; that K is written here before the fit runs.

**Proposed:** K is not fixed; it is the K that minimises the description length (lowest level of the nested model, or the flat model's K).

**Was put as:** whether to also fit the SBM with K fixed to the number of clusters chosen in §3, so the §4.3 comparison is between partitions of the same size. That K does not exist yet. If yes, it is fixed when the §3 clustering is decided, before the SBM runs.

### G8. Randomness and runs

**Decided: as proposed.**

The fit is a stochastic search; different seeds can give different partitions.

**Proposed:**
- 10 independent fits for each model, seeds 42 to 51. For each seed: `graph_tool.seed_rng(seed)` and `numpy.random.seed(seed)`, one thread (`graph_tool.openmp_set_num_threads(1)`).
- Each fit is `minimize_nested_blockmodel_dl` followed by 100 refinement sweeps (`multiflip_mcmc_sweep`, `niter=10`, repeated 100 times).
- The fit with the lowest description length is the result. The spread across the 10 is reported: each fit's description length and number of blocks, and the NMI between each fit's partition and the kept one.
- The G3 extra fit (with self-loops) uses the same procedure; the comparison is the NMI and adjusted Rand index between its kept partition and the main one, plus the contingency table.
- If one fit takes too long to run 10, the number of fits or sweeps is lowered **before** any partition is looked at; runtime is not a result.

**Other options:** fewer fits; a different number of sweeps. I have no source for 10 or 100; they are our own numbers.

Reproducibility: repeat runs on your Mac with the same seeds should give the same result (not verified). The same result on another machine is not expected. The cloud cannot run this stage.

### G9. One graph or several

The central question asks about « l'évolution du réseau ».

**Decided: (a).**

- (a) One graph for all of 2025. Evolution is left to §3 (profiles by month or season) and §2.3.
- (b) The 2025 graph plus graphs for periods decided now (for example each month, or weekdays against weekends), each fitted the same way. Comparing their partitions adds a run per period.
- (c) A layered SBM with periods as layers (Peixoto, 2015). This is the most direct model of change over time, and the most work.

## What the stages write

`src/graph.py` (env_311):
- `data/interim/edges.csv`: `source`, `target`, `weight`, `is_self_loop`; one row per pair with w_ij ≥ 1, sorted by source then target.
- `output/runs/graph/<UTC>/`: `run.json` with the number of nodes, edges, self-loops and total weight.

`src/sbm.py` (Python 3.15):
- `output/runs/sbm/<UTC>/`:
  - `blocks.csv`: `station_id` and the block at each level, for the kept fit of each model.
  - `fits.csv`: for each model and seed, the description length and the number of blocks at each level.
  - `run.json`: graph-tool and numpy versions, seeds, the model settings above.

Later stages (figures, §4.3) read these in env_311. The §4.3 comparison gets its own note.

## References

Citations from memory; to check before they go in the report.

- Holland, P. W., Laskey, K. B., & Leinhardt, S. (1983). Stochastic blockmodels: First steps. *Social Networks, 5*(2), 109–137.
- Karrer, B., & Newman, M. E. J. (2011). Stochastic blockmodels and community structure in networks. *Physical Review E, 83*(1), 016107.
- Peixoto, T. P. (2014). Hierarchical block structures and high-resolution model selection in large networks. *Physical Review X, 4*(1), 011047.
- Peixoto, T. P. (2015). Inferring the mesoscale structure of layered, edge-valued, and time-varying networks. *Physical Review E, 92*(4), 042807.
- Peixoto, T. P. (2017). Nonparametric Bayesian inference of the microcanonical stochastic block model. *Physical Review E, 95*(1), 012317.
- Peixoto, T. P. (2018). Nonparametric weighted stochastic block models. *Physical Review E, 97*(1), 012306.
