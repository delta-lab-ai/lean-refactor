import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat


theorem atlas_17373 (X : ℕ → ℝ) (f : ℝ → ℝ) (hf : f = fun x => Real.sin x) (h : ∀ ε > 0, ∃ N, ∀ n ≥ N, |X n| < ε) (ε : ℝ) (hε : ε > 0) : ∃ N, ∀ n ≥ N, |Real.sin (X n)| < ε := by
  rcases h ε hε with ⟨N, hN⟩
  refine ⟨N, ?_⟩
  intro n hn
  exact lt_of_le_of_lt abs_sin_le_abs (hN n hn)