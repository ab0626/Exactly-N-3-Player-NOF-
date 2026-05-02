"""Exactly-N (3-player NOF) mini research environment."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import html
import math
import random
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


Pair = Tuple[int, int]


def _base_digits(value: int, base: int, width: int) -> List[int]:
    digits = [0] * width
    x = value
    for i in range(width):
        digits[i] = x % base
        x //= base
    return digits


def behrend_3ap_free_set(limit: int, base: int = 8, bucket_rank: int = 0) -> Set[int]:
    """Build a Behrend-style 3AP-free set inside {0, ..., limit-1}."""
    if limit <= 0:
        return set()
    width = max(1, math.floor(math.log(max(limit - 1, 1), base)) + 1)
    digit_max = max(1, base // 2)
    buckets: Dict[int, List[int]] = {}
    total = digit_max**width

    for idx in range(total):
        digits = _base_digits(idx, digit_max, width)
        value = 0
        power = 1
        sq_norm = 0
        for d in digits:
            value += d * power
            sq_norm += d * d
            power *= base
        if value < limit:
            buckets.setdefault(sq_norm, []).append(value)

    if not buckets:
        return set()
    sorted_buckets = sorted(buckets.items(), key=lambda item: len(item[1]), reverse=True)
    use_rank = min(max(bucket_rank, 0), len(sorted_buckets) - 1)
    return set(sorted_buckets[use_rank][1])


def corner_free_lookup_from_behrend(
    domain_size: int,
    base: int = 8,
    bucket_rank: int = 0,
    thinning: float = 1.0,
    seed: int = 0,
) -> Set[Pair]:
    """
    Build a corner-free lookup A subset of [0, domain_size)^2.
    A = {(x, y): (x - y) mod domain_size in B}, where B is 3AP-free.
    """
    bset = behrend_3ap_free_set(domain_size, base=base, bucket_rank=bucket_rank)
    lookup: Set[Pair] = set()
    rng = random.Random(seed)
    keep_prob = min(max(thinning, 0.0), 1.0)
    for x in range(domain_size):
        for y in range(domain_size):
            if ((x - y) % domain_size) in bset and rng.random() <= keep_prob:
                lookup.add((x, y))
    return lookup


@dataclass(frozen=True)
class PlayerMessage:
    player: str
    own_guess_mod_p: int
    certificate_bit: int
    bits_sent: int


@dataclass(frozen=True)
class NondetCertificate:
    pair_xy: Pair
    bits: int


class Prover:
    """Nondeterministic prover: suggests a certificate (x, y) if possible."""

    def propose(self, x: int, y: int, z: int, target_n: int, lookup: Set[Pair], domain_size: int) -> Optional[NondetCertificate]:
        if x + y + z != target_n:
            return None
        cert_pair = (x % domain_size, y % domain_size)
        if cert_pair not in lookup:
            return None
        bits = 2 * math.ceil(math.log2(max(2, domain_size)))
        return NondetCertificate(pair_xy=cert_pair, bits=bits)


class Player:
    """NOF player that sends compact deterministic message."""

    def __init__(self, name: str, prime_modulus: int, corner_lookup: Set[Pair], domain_size: int) -> None:
        self.name = name
        self.p = prime_modulus
        self.corner_lookup = corner_lookup
        self.domain_size = domain_size

    def send(self, seen_a: int, seen_b: int, target_n: int) -> PlayerMessage:
        implied_own = target_n - seen_a - seen_b
        implied_mod = implied_own % self.p
        if 0 <= implied_own < self.domain_size:
            cert = int(
                (seen_a % self.domain_size, implied_own) in self.corner_lookup
                or (implied_own, seen_b % self.domain_size) in self.corner_lookup
            )
        else:
            cert = 0
        bits = math.ceil(math.log2(self.p)) + 1
        return PlayerMessage(self.name, implied_mod, cert, bits)


class Referee:
    """Referee for deterministic and nondeterministic protocol variants."""

    def __init__(
        self,
        domain_size: int,
        target_n: int,
        prime_modulus: int = 17,
        behrend_base: int = 8,
        bucket_rank: int = 0,
        thinning: float = 1.0,
        seed: int = 0,
    ) -> None:
        self.domain_size = domain_size
        self.target_n = target_n
        self.prime_modulus = prime_modulus
        self.corner_lookup = corner_free_lookup_from_behrend(
            domain_size=domain_size,
            base=behrend_base,
            bucket_rank=bucket_rank,
            thinning=thinning,
            seed=seed,
        )
        self.alice = Player("Alice", prime_modulus, self.corner_lookup, domain_size)
        self.bob = Player("Bob", prime_modulus, self.corner_lookup, domain_size)
        self.charlie = Player("Charlie", prime_modulus, self.corner_lookup, domain_size)
        self.prover = Prover()

    def run_round(self, x: int, y: int, z: int) -> Dict[str, object]:
        m_a = self.alice.send(y, z, self.target_n)
        m_b = self.bob.send(x, z, self.target_n)
        m_c = self.charlie.send(x, y, self.target_n)
        messages = [m_a, m_b, m_c]
        modular_sum = (m_a.own_guess_mod_p + m_b.own_guess_mod_p + m_c.own_guess_mod_p) % self.prime_modulus
        modular_ok = modular_sum == (self.target_n % self.prime_modulus)
        cert_votes = m_a.certificate_bit + m_b.certificate_bit + m_c.certificate_bit
        guess_yes = modular_ok and cert_votes >= 1
        truth_yes = (x + y + z == self.target_n)
        bits_total = sum(m.bits_sent for m in messages)
        return {
            "guess_yes": guess_yes,
            "truth_yes": truth_yes,
            "correct": guess_yes == truth_yes,
            "bits_total": bits_total,
        }

    def run_nondet_round(self, x: int, y: int, z: int) -> Dict[str, object]:
        cert = self.prover.propose(x, y, z, self.target_n, self.corner_lookup, self.domain_size)
        truth_yes = (x + y + z == self.target_n)
        if cert is None:
            return {
                "guess_yes": False,
                "truth_yes": truth_yes,
                "correct": not truth_yes,
                "bits_total": 0,
                "certificate_bits": 0,
                "accepted_players": 0,
            }

        cx, cy = cert.pair_xy
        # Local NOF checks using only seen pair + certificate.
        alice_implied_x = self.target_n - y - z
        bob_implied_y = self.target_n - x - z
        alice_ok = (0 <= alice_implied_x < self.domain_size) and (cx == alice_implied_x) and (cy == y)
        bob_ok = (0 <= bob_implied_y < self.domain_size) and (cx == x) and (cy == bob_implied_y)
        charlie_ok = (cx == x) and (cy == y)
        lookup_ok = cert.pair_xy in self.corner_lookup
        accepts = [alice_ok and lookup_ok, bob_ok and lookup_ok, charlie_ok and lookup_ok]
        accepted_players = sum(1 for ok in accepts if ok)
        guess_yes = all(accepts)
        bits_total = cert.bits + 3  # certificate + one accept/reject bit per player
        return {
            "guess_yes": guess_yes,
            "truth_yes": truth_yes,
            "correct": guess_yes == truth_yes,
            "bits_total": bits_total,
            "certificate_bits": cert.bits,
            "accepted_players": accepted_players,
        }

    def _simulate_generic(self, rounds: int, seed: int, nondet: bool) -> Dict[str, object]:
        rng = random.Random(seed)
        correct = 0
        tp = fp = tn = fn = 0
        total_bits = 0
        for _ in range(rounds):
            x = rng.randrange(self.domain_size)
            y = rng.randrange(self.domain_size)
            z = rng.randrange(self.domain_size)
            result = self.run_nondet_round(x, y, z) if nondet else self.run_round(x, y, z)
            total_bits += int(result["bits_total"])
            if result["correct"]:
                correct += 1
            if result["truth_yes"] and result["guess_yes"]:
                tp += 1
            elif (not result["truth_yes"]) and result["guess_yes"]:
                fp += 1
            elif (not result["truth_yes"]) and (not result["guess_yes"]):
                tn += 1
            else:
                fn += 1
        return {
            "rounds": rounds,
            "accuracy": correct / rounds if rounds else 0.0,
            "avg_bits_per_round": total_bits / rounds if rounds else 0.0,
            "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
            "lookup_density": len(self.corner_lookup) / (self.domain_size * self.domain_size),
            "lookup_size": len(self.corner_lookup),
        }

    def simulate(self, rounds: int = 1000, seed: int = 0) -> Dict[str, object]:
        return self._simulate_generic(rounds=rounds, seed=seed, nondet=False)

    def simulate_nondet(self, rounds: int = 1000, seed: int = 0) -> Dict[str, object]:
        return self._simulate_generic(rounds=rounds, seed=seed, nondet=True)


def _safe_loglog(n: int) -> float:
    return math.log(max(math.log(max(float(n), 3.0)), 1.000001))


def run_sweeps(
    output_dir: Path,
    rounds: int = 2000,
    seed: int = 0,
    figures_dir: Optional[Path] = None,
    png_plots: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if figures_dir is None:
        figures_dir = Path("docs") / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    domain_sizes = [32, 64, 128, 256]
    bases = [6, 8, 10]
    thinnings = [1.0, 0.7, 0.4]
    moduli = [17, 31, 61]
    rows: List[Dict[str, object]] = []

    for n in domain_sizes:
        target_n = n - 1
        for base in bases:
            for thinning in thinnings:
                for p in moduli:
                    ref = Referee(
                        domain_size=n,
                        target_n=target_n,
                        prime_modulus=p,
                        behrend_base=base,
                        bucket_rank=0,
                        thinning=thinning,
                        seed=seed,
                    )
                    det = ref.simulate(rounds=rounds, seed=seed + 11)
                    nd = ref.simulate_nondet(rounds=rounds, seed=seed + 29)
                    logn = math.log(max(n, 2))
                    row = {
                        "domain_size": n,
                        "behrend_base": base,
                        "thinning": thinning,
                        "prime_modulus": p,
                        "lookup_density": det["lookup_density"],
                        "det_accuracy": det["accuracy"],
                        "det_avg_bits": det["avg_bits_per_round"],
                        "nondet_accuracy": nd["accuracy"],
                        "nondet_avg_bits": nd["avg_bits_per_round"],
                        # Heuristic reference curves for visualization.
                        "old_density_curve_1_over_loglogN": 1.0 / max(_safe_loglog(n), 1e-9),
                        "new_density_curve_exp_logN_0p2": math.exp(-(logn ** 0.2)),
                        "theory_lb_quasipoly_like": logn ** 0.2,
                    }
                    rows.append(row)

    csv_path = output_dir / "sweep_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary_path = output_dir / "summary_table.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as fp:
        fieldnames = [
            "domain_size",
            "mean_lookup_density",
            "mean_det_bits",
            "mean_nondet_bits",
            "mean_det_accuracy",
            "mean_nondet_accuracy",
            "theory_lb_quasipoly_like",
        ]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for n in domain_sizes:
            subset = [r for r in rows if r["domain_size"] == n]
            writer.writerow(
                {
                    "domain_size": n,
                    "mean_lookup_density": sum(float(r["lookup_density"]) for r in subset) / len(subset),
                    "mean_det_bits": sum(float(r["det_avg_bits"]) for r in subset) / len(subset),
                    "mean_nondet_bits": sum(float(r["nondet_avg_bits"]) for r in subset) / len(subset),
                    "mean_det_accuracy": sum(float(r["det_accuracy"]) for r in subset) / len(subset),
                    "mean_nondet_accuracy": sum(float(r["nondet_accuracy"]) for r in subset) / len(subset),
                    "theory_lb_quasipoly_like": math.log(n) ** 0.2,
                }
            )

    _try_make_plots(rows, output_dir=output_dir, figures_dir=figures_dir, png_plots=png_plots)
    print(f"Sweep complete. Wrote: {csv_path}, {summary_path}")


def _aggregate_plot_series(rows: List[Dict[str, object]]) -> Dict[str, List[float]]:
    domain_sizes = sorted({int(r["domain_size"]) for r in rows})
    mean_density: List[float] = []
    old_curve: List[float] = []
    new_curve: List[float] = []
    det_bits: List[float] = []
    nondet_bits: List[float] = []
    theory_lb: List[float] = []

    for n in domain_sizes:
        subset = [r for r in rows if int(r["domain_size"]) == n]
        mean_density.append(sum(float(r["lookup_density"]) for r in subset) / len(subset))
        old_curve.append(sum(float(r["old_density_curve_1_over_loglogN"]) for r in subset) / len(subset))
        new_curve.append(sum(float(r["new_density_curve_exp_logN_0p2"]) for r in subset) / len(subset))
        det_bits.append(sum(float(r["det_avg_bits"]) for r in subset) / len(subset))
        nondet_bits.append(sum(float(r["nondet_avg_bits"]) for r in subset) / len(subset))
        theory_lb.append(sum(float(r["theory_lb_quasipoly_like"]) for r in subset) / len(subset))

    return {
        "domain_sizes": [float(n) for n in domain_sizes],
        "mean_density": mean_density,
        "old_curve": old_curve,
        "new_curve": new_curve,
        "det_bits": det_bits,
        "nondet_bits": nondet_bits,
        "theory_lb": theory_lb,
    }


def _svg_escape(text: str) -> str:
    return html.escape(text, quote=True)


def _write_multi_series_svg(
    path: Path,
    title: str,
    x_values: List[float],
    series: List[Dict[str, object]],
    *,
    x_log2: bool,
    y_log10: bool,
    x_label: str,
    y_label: str,
    width: int = 900,
    height: int = 520,
) -> None:
    pad_l, pad_r, pad_t, pad_b = 90, 220, 70, 70
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    xs = [float(v) for v in x_values]
    if x_log2:
        x_src = [math.log(max(v, 1.0), 2) for v in xs]
    else:
        x_src = xs

    transformed_series: List[Dict[str, object]] = []
    all_y_plot: List[float] = []
    y_eps = 1e-12
    for s in series:
        y_vals = [float(v) for v in s["y"]]  # type: ignore[index]
        if y_log10:
            y_plot = [math.log10(max(y, y_eps)) for y in y_vals]
        else:
            y_plot = y_vals
        all_y_plot.extend(y_plot)
        transformed_series.append({"meta": s, "y_plot": y_plot})

    x_min, x_max = min(x_src), max(x_src)
    y_min, y_max = min(all_y_plot), max(all_y_plot)
    if x_max - x_min < 1e-12:
        x_min -= 1e-6
        x_max += 1e-6
    if y_max - y_min < 1e-12:
        y_min -= 1e-6
        y_max += 1e-6

    def x_to_px(xv: float) -> float:
        return pad_l + (xv - x_min) / (x_max - x_min) * plot_w

    def y_to_px(yv: float) -> float:
        return pad_t + (y_max - yv) / (y_max - y_min) * plot_h

    parts: List[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<text x="{pad_l}" y="40" font-size="20" font-family="Segoe UI, Arial, sans-serif" fill="#111827">{_svg_escape(title)}</text>')

    # Plot frame
    parts.append(
        f'<rect x="{pad_l}" y="{pad_t}" width="{plot_w}" height="{plot_h}" fill="#fafafa" stroke="#d1d5db" stroke-width="1"/>'
    )

    # Axis labels
    parts.append(
        f'<text x="{pad_l + plot_w / 2}" y="{height - 25}" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#374151">{_svg_escape(x_label)}</text>'
    )
    parts.append(
        f'<text transform="translate(28,{pad_t + plot_h / 2}) rotate(-90)" text-anchor="middle" font-size="14" font-family="Segoe UI, Arial, sans-serif" fill="#374151">{_svg_escape(y_label)}</text>'
    )

    legend_x = pad_l + plot_w + 18
    legend_y = pad_t + 18

    color_cycle = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ca8a04", "#0f766e"]
    for idx, item in enumerate(transformed_series):
        s = item["meta"]  # type: ignore[assignment]
        y_plot = [float(v) for v in item["y_plot"]]  # type: ignore[index]
        color = str(s.get("color", color_cycle[idx % len(color_cycle)]))
        label = str(s["label"])

        if x_log2:
            x_plot = [math.log(max(v, 1.0), 2) for v in xs]
        else:
            x_plot = xs

        pts = list(zip(x_plot, y_plot))

        d_parts = []
        for i, (xv, yv) in enumerate(pts):
            px = x_to_px(xv)
            py = y_to_px(yv)
            d_parts.append(f"{'M' if i == 0 else 'L'} {px:.2f} {py:.2f}")
        parts.append(f'<path d="{" ".join(d_parts)}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for xv, yv in pts:
            px = x_to_px(xv)
            py = y_to_px(yv)
            parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4" fill="{color}"/>')

        # Legend row
        ly = legend_y + idx * 22
        parts.append(f'<rect x="{legend_x}" y="{ly - 10}" width="14" height="14" fill="{color}"/>')
        parts.append(
            f'<text x="{legend_x + 22}" y="{ly + 2}" font-size="13" font-family="Segoe UI, Arial, sans-serif" fill="#111827">{_svg_escape(label)}</text>'
        )

    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _write_sweep_figures_svg(series: Dict[str, List[float]], figures_dir: Path) -> None:
    xs = series["domain_sizes"]
    _write_multi_series_svg(
        figures_dir / "density_vs_grid.svg",
        "Density vs grid size (log-log)",
        xs,
        [
            {"label": "Observed mean lookup density", "y": series["mean_density"], "color": "#2563eb"},
            {"label": "Reference: ~1 / log log N", "y": series["old_curve"], "color": "#dc2626"},
            {"label": "Reference: exp(-(log N)^0.2)", "y": series["new_curve"], "color": "#16a34a"},
        ],
        x_log2=True,
        y_log10=True,
        x_label="Grid size N (log2 axis)",
        y_label="Density (log10 axis)",
    )
    _write_multi_series_svg(
        figures_dir / "communication_cost.svg",
        "Communication cost vs grid size",
        xs,
        [
            {"label": "Mean deterministic bits / round", "y": series["det_bits"], "color": "#2563eb"},
            {"label": "Mean nondeterministic bits / round", "y": series["nondet_bits"], "color": "#dc2626"},
            {"label": "Reference curve: (log N)^0.2", "y": series["theory_lb"], "color": "#16a34a"},
        ],
        x_log2=True,
        y_log10=False,
        x_label="Grid size N (log2 axis)",
        y_label="Bits (linear axis)",
    )


def _try_make_plots(rows: List[Dict[str, object]], *, output_dir: Path, figures_dir: Path, png_plots: bool) -> None:
    series = _aggregate_plot_series(rows)
    _write_sweep_figures_svg(series, figures_dir)
    print(f"Figures (SVG) written under: {figures_dir}")

    if not png_plots:
        print("PNG plots skipped (pass --png-plots to attempt matplotlib PNG export).")
        return

    try:
        import matplotlib.pyplot as plt  # type: ignore[reportMissingImports]
    except Exception:
        print("matplotlib not available; PNG plots skipped (SVG figures were still generated).")
        return

    domain_sizes_int = [int(x) for x in series["domain_sizes"]]
    plt.figure(figsize=(8, 5))
    plt.plot(domain_sizes_int, series["mean_density"], marker="o", label="Observed lookup density")
    plt.plot(domain_sizes_int, series["old_curve"], marker="x", label="Old-style 1/loglog N curve")
    plt.plot(domain_sizes_int, series["new_curve"], marker="s", label="Quasipoly-like exp(-(log N)^0.2)")
    plt.xscale("log", base=2)
    plt.yscale("log")
    plt.xlabel("Grid size N")
    plt.ylabel("Density")
    plt.title("Density vs Grid Size")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "plot_density_vs_grid.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.plot(domain_sizes_int, series["det_bits"], marker="o", label="Deterministic simulation bits")
    plt.plot(domain_sizes_int, series["nondet_bits"], marker="x", label="Nondeterministic simulation bits")
    plt.plot(domain_sizes_int, series["theory_lb"], marker="s", label="Cor.1.7-style LB shape (log N)^0.2")
    plt.xscale("log", base=2)
    plt.xlabel("Grid size N")
    plt.ylabel("Bits")
    plt.title("Communication Cost vs Grid Size")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "plot_communication_cost.png", dpi=160)
    plt.close()

    print(f"Plots (PNG) written under: {output_dir}")


def _load_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _float_value(row: Dict[str, str], key: str) -> float:
    return float(row[key])


def generate_report(output_dir: Path, report_filename: str = "report.md") -> Path:
    sweep_path = output_dir / "sweep_results.csv"
    summary_path = output_dir / "summary_table.csv"
    sweep_rows = _load_csv_rows(sweep_path)
    summary_rows = _load_csv_rows(summary_path)
    if not sweep_rows or not summary_rows:
        raise FileNotFoundError(
            "Missing sweep CSV data. Run --mode sweep first to produce outputs/sweep_results.csv and outputs/summary_table.csv."
        )

    best_det = max(sweep_rows, key=lambda r: _float_value(r, "det_accuracy"))
    best_nondet = max(sweep_rows, key=lambda r: _float_value(r, "nondet_accuracy"))
    min_det_bits = min(sweep_rows, key=lambda r: _float_value(r, "det_avg_bits"))
    min_nondet_bits = min(sweep_rows, key=lambda r: _float_value(r, "nondet_avg_bits"))

    summary_sorted = sorted(summary_rows, key=lambda r: int(r["domain_size"]))
    first = summary_sorted[0]
    last = summary_sorted[-1]

    density_drop = _float_value(last, "mean_lookup_density") - _float_value(first, "mean_lookup_density")
    det_bits_growth = _float_value(last, "mean_det_bits") - _float_value(first, "mean_det_bits")
    nondet_bits_growth = _float_value(last, "mean_nondet_bits") - _float_value(first, "mean_nondet_bits")
    theory_growth = _float_value(last, "theory_lb_quasipoly_like") - _float_value(first, "theory_lb_quasipoly_like")

    report_path = output_dir / report_filename
    lines: List[str] = []
    lines.append("# Exactly-N Mini-Lab Report")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- Sweep file: `{sweep_path}`")
    lines.append(f"- Summary file: `{summary_path}`")
    lines.append(f"- Number of sweep configurations: {len(sweep_rows)}")
    lines.append("")
    lines.append("## Best configurations")
    lines.append(
        "- Best deterministic accuracy: "
        f"{_float_value(best_det, 'det_accuracy'):.4f} at "
        f"N={best_det['domain_size']}, base={best_det['behrend_base']}, "
        f"thinning={best_det['thinning']}, p={best_det['prime_modulus']}, "
        f"bits={_float_value(best_det, 'det_avg_bits'):.3f}"
    )
    lines.append(
        "- Best nondeterministic accuracy: "
        f"{_float_value(best_nondet, 'nondet_accuracy'):.4f} at "
        f"N={best_nondet['domain_size']}, base={best_nondet['behrend_base']}, "
        f"thinning={best_nondet['thinning']}, p={best_nondet['prime_modulus']}, "
        f"bits={_float_value(best_nondet, 'nondet_avg_bits'):.3f}"
    )
    lines.append(
        "- Lowest deterministic communication: "
        f"{_float_value(min_det_bits, 'det_avg_bits'):.3f} bits at "
        f"N={min_det_bits['domain_size']}, base={min_det_bits['behrend_base']}, "
        f"thinning={min_det_bits['thinning']}, p={min_det_bits['prime_modulus']}"
    )
    lines.append(
        "- Lowest nondeterministic communication: "
        f"{_float_value(min_nondet_bits, 'nondet_avg_bits'):.3f} bits at "
        f"N={min_nondet_bits['domain_size']}, base={min_nondet_bits['behrend_base']}, "
        f"thinning={min_nondet_bits['thinning']}, p={min_nondet_bits['prime_modulus']}"
    )
    lines.append("")
    lines.append("## Scaling snapshot")
    lines.append(
        f"- Mean lookup density from N={first['domain_size']} to N={last['domain_size']}: "
        f"{_float_value(first, 'mean_lookup_density'):.6f} -> {_float_value(last, 'mean_lookup_density'):.6f} "
        f"(delta {density_drop:+.6f})"
    )
    lines.append(
        f"- Mean deterministic bits: {_float_value(first, 'mean_det_bits'):.3f} -> "
        f"{_float_value(last, 'mean_det_bits'):.3f} (delta {det_bits_growth:+.3f})"
    )
    lines.append(
        f"- Mean nondeterministic bits: {_float_value(first, 'mean_nondet_bits'):.3f} -> "
        f"{_float_value(last, 'mean_nondet_bits'):.3f} (delta {nondet_bits_growth:+.3f})"
    )
    lines.append(
        f"- Theory lower-bound proxy (log N)^0.2: {_float_value(first, 'theory_lb_quasipoly_like'):.3f} -> "
        f"{_float_value(last, 'theory_lb_quasipoly_like'):.3f} (delta {theory_growth:+.3f})"
    )
    lines.append("")
    lines.append("## Paper alignment notes")
    lines.append(
        "- Nondeterministic certificate mode mirrors the NOF flavor of Corollary 1.7: a shared witness is locally checked by each player."
    )
    lines.append(
        "- Density controls verification opportunities: thinning the lookup generally reduces accepted witnesses and changes communication-accuracy tradeoffs."
    )
    lines.append(
        "- The report uses heuristic reference curves for intuition; it is a computational probe, not a proof of the quasipolynomial bound."
    )
    lines.append("")
    lines.append("## Next experiments")
    lines.append("- Increase rounds for tighter confidence intervals.")
    lines.append("- Add confidence bands and false-positive/false-negative trend charts.")
    lines.append("- Compare multiple certificate encodings (index, hash, pair coordinates).")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def demo() -> None:
    domain = 64
    target_n = 63
    ref = Referee(domain_size=domain, target_n=target_n, prime_modulus=31, behrend_base=8, thinning=1.0)
    print("Exactly-N 3-player NOF mini lab")
    print(f"Domain [0, {domain - 1}], target={target_n}, lookup_size={len(ref.corner_lookup)}")

    sample = ref.run_round(10, 20, 33)
    print("Deterministic sample:", sample)

    sample_nd = ref.run_nondet_round(10, 20, 33)
    print("Nondeterministic sample:", sample_nd)

    print("Deterministic stats:", ref.simulate(rounds=2000, seed=42))
    print("Nondeterministic stats:", ref.simulate_nondet(rounds=2000, seed=42))


def main() -> None:
    parser = argparse.ArgumentParser(description="Exactly-N NOF mini research environment")
    parser.add_argument("--mode", choices=["demo", "sweep", "report"], default="demo")
    parser.add_argument("--rounds", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--figures-dir", default=str(Path("docs") / "figures"))
    parser.add_argument(
        "--png-plots",
        action="store_true",
        help="Also try to write PNG plots to --output-dir using matplotlib (optional; may fail depending on your Python/numpy stack).",
    )
    args = parser.parse_args()

    if args.mode == "demo":
        demo()
        return
    if args.mode == "sweep":
        run_sweeps(
            output_dir=Path(args.output_dir),
            rounds=args.rounds,
            seed=args.seed,
            figures_dir=Path(args.figures_dir),
            png_plots=args.png_plots,
        )
        return
    report_path = generate_report(output_dir=Path(args.output_dir))
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    main()
