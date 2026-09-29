import Analysis.MeasureTheory.Section_1_3_1

/-!
# Introduction to Measure Theory, Section 1.3.2: Measurable functions

A companion to (the introduction to) Section 1.3.2 of the book "An introduction to Measure Theory".

-/

def Unsigned {X Y:Type*} [LE Y] [Zero Y] (f:X → Y) : Prop := ∀ x, f x ≥ 0

def PointwiseConvergesTo {X Y:Type*} [TopologicalSpace Y] (f: ℕ → X → Y) (g: X → Y) : Prop := ∀ x, Filter.atTop.Tendsto (fun n ↦ f n x) (nhds (g x))

/-- Definiiton 1.3.8 (Unsigned measurable function) -/
def UnsignedMeasurable {d:ℕ} (f: EuclideanSpace' d → EReal) : Prop := Unsigned f ∧ ∃ (g: ℕ → EuclideanSpace' d → EReal), (∀ n, UnsignedSimpleFunction (g n)) ∧ (PointwiseConvergesTo g f)

def EReal.BoundedFunction {X:Type*} (f:X → EReal) : Prop := ∃ M:NNReal, ∀ x, (f x).abs ≤ M

def FiniteMeasureSupport {d:ℕ} {Y:Type*} [Zero Y] (f: EuclideanSpace' d → Y) : Prop := Lebesgue_measure (Support f) < ⊤

def PointwiseAeConvergesTo {d:ℕ} {Y:Type*} [TopologicalSpace Y] (f: ℕ → (EuclideanSpace' d → Y)) (g: EuclideanSpace' d → Y) : Prop := AlmostAlways (fun x ↦ Filter.atTop.Tendsto (fun n ↦ f n x) (nhds (g x)))

/-- Lemma 1.3.9 (Equivalent notions of measurability).  Some slight changes to the statement have been made to make the claims cleaner to state -/
theorem UnsignedMeasurable.TFAE {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: Unsigned f):
    [
      UnsignedMeasurable f,
      ∃ (g: ℕ → EuclideanSpace' d → EReal), (∀ n, UnsignedSimpleFunction (g n)) ∧ (∀ x, Filter.atTop.Tendsto (fun n ↦ g n x) (nhds (f x))),
      ∃ (g: ℕ → EuclideanSpace' d → EReal), (∀ n, UnsignedSimpleFunction (g n)) ∧ (PointwiseAeConvergesTo g f),
      ∃ (g: ℕ → EuclideanSpace' d → EReal), (∀ n, UnsignedSimpleFunction (g n) ∧  EReal.BoundedFunction (g n) ∧ FiniteMeasureSupport (g n)) ∧ (∀ x, Monotone (fun n ↦ g n x)) ∧ (∀ x, f x = iSup (fun n ↦ g n x)),
      ∀ t, MeasurableSet {x | f x > t},
      ∀ t, MeasurableSet {x | f x ≥ t},
      ∀ t, MeasurableSet {x | f x < t},
      ∀ t, MeasurableSet {x | f x ≤ t},
      ∀ I:BoundedInterval, MeasurableSet (f⁻¹' (Real.toEReal '' I.toSet)),
      ∀ U: Set EReal, IsOpen U → MeasurableSet (f⁻¹' U),
      ∀ K: Set EReal, IsClosed K → MeasurableSet (f⁻¹' K)
    ].TFAE
  := by sorry

/-- Exercise 1.3.3(i) -/
theorem Continuous.UnsignedMeasurable {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: Continuous f) (hnonneg: Unsigned f): UnsignedMeasurable f := by sorry

/-- Exercise 1.3.3(ii) -/
theorem UnsignedSimpleFunction.unsignedMeasurable {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f): UnsignedMeasurable f := by sorry

/-- Exercise 1.3.3(iii) -/
theorem UnsignedMeasurable.sup {d:ℕ} {f: ℕ → EuclideanSpace' d → EReal} (hf: ∀ n, UnsignedMeasurable (f n)) : UnsignedMeasurable (fun x ↦ iSup (fun n ↦ f n x)) := by sorry

/-- Exercise 1.3.3(iii) -/
theorem UnsignedMeasurable.inf {d:ℕ} {f: ℕ → EuclideanSpace' d → EReal} (hf: ∀ n, UnsignedMeasurable (f n)) : UnsignedMeasurable (fun x ↦ iInf (fun n ↦ f n x)) := by sorry

/-- Exercise 1.3.3(iii) -/
theorem UnsignedMeasurable.limsup {d:ℕ} {f: ℕ → EuclideanSpace' d → EReal} (hf: ∀ n, UnsignedMeasurable (f n)) : UnsignedMeasurable (fun x ↦ Filter.atTop.limsup (fun n ↦ f n x) ) := by sorry

/-- Exercise 1.3.3(iii) -/
theorem UnsignedMeasurable.liminf {d:ℕ} {f: ℕ → EuclideanSpace' d → EReal} (hf: ∀ n, UnsignedMeasurable (f n)) : UnsignedMeasurable (fun x ↦ Filter.atTop.liminf (fun n ↦ f n x) ) := by sorry

/-- Exercise 1.3.3(iv) -/
theorem UnsignedMeasurable.aeEqual {d:ℕ} {f g: EuclideanSpace' d → EReal} (hf: UnsignedMeasurable f) (heq: AlmostEverywhereEqual f g) : UnsignedMeasurable g := by sorry

/-- Exercise 1.3.3(v) -/
theorem UnsignedMeasurable.aeLimit {d:ℕ} {f: EuclideanSpace' d → EReal} (g: ℕ → EuclideanSpace' d → EReal) (hf: ∀ n, UnsignedMeasurable (g n)) (heq: PointwiseAeConvergesTo g f) : UnsignedMeasurable f := by sorry

/-- Exercise 1.3.3(vi) -/
theorem UnsignedMeasurable.comp_cts {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedMeasurable f) {φ: EReal → EReal} (hφ: Continuous φ)  : UnsignedMeasurable (φ ∘ f) := by sorry

/-- Exercise 1.3.3(vii) -/
theorem UnsignedMeasurable.add {d:ℕ} {f g: EuclideanSpace' d → EReal} (hf: UnsignedMeasurable f) (hg: UnsignedMeasurable g) : UnsignedMeasurable (f + g) := by sorry

def UniformConvergesTo {X:Type*} (f: ℕ → X → EReal) (g: X → EReal) : Prop := ∀ ε:NNReal, ε > 0 → ∃ N:ℕ, ∀ n ≥ N, ∀ x, f n x > g x - ε ∧ f n x < g x + ε

/-- Exercise 1.3.4 -/
theorem UnsignedMeasurable.bounded_iff {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: Unsigned f) : UnsignedMeasurable f ∧ EReal.BoundedFunction f ↔ ∃ g : ℕ → EuclideanSpace' d → EReal, (∀ n, UnsignedSimpleFunction (g n) ∧ EReal.BoundedFunction (g n)) ∧ UniformConvergesTo g f := by sorry

/-- Exercise 1.3.5 -/
theorem UnsignedSimpleFunction.iff {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: Unsigned f) : UnsignedSimpleFunction f ↔ UnsignedMeasurable f ∧ Finite (f '' Set.univ) := by sorry

/-- Exercise 1.3.6 -/
theorem UnsignedMeasurable.measurable_graph {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedMeasurable f) : LebesgueMeasurable { p | ∃ x, ∃ t:ℝ, EuclideanSpace'.prod_equiv d 1 p = ⟨ x, t ⟩ ∧ 0 ≤ t ∧ t ≤ f x } := by sorry

/-- Remark 1.3.10 -/
example : ∃ (f: EuclideanSpace' 1 → EReal) (hf: UnsignedMeasurable f) (E: Set (EuclideanSpace' 1)) (hE: LebesgueMeasurable E), ¬ LebesgueMeasurable (f⁻¹' ((Real.toEReal ∘ EuclideanSpace'.equiv_Real) '' E)) := by sorry

/-- Definition 1.3.11 (Complex measurability)-/
def ComplexMeasurable {d:ℕ} (f: EuclideanSpace' d → ℂ) : Prop := ∃ (g: ℕ → EuclideanSpace' d → ℂ), (∀ n, ComplexSimpleFunction (g n)) ∧ (PointwiseConvergesTo g f)

def RealMeasurable {d:ℕ} (f: EuclideanSpace' d → ℝ) : Prop := ∃ (g: ℕ → EuclideanSpace' d → ℝ), (∀ n, RealSimpleFunction (g n)) ∧ (PointwiseConvergesTo g f)

theorem RealMeasurable.iff {d:ℕ} {f: EuclideanSpace' d → ℝ} : RealMeasurable f ↔ ComplexMeasurable (Real.complex_fun f) := by sorry

theorem ComplexMeasurable.iff {d:ℕ} {f: EuclideanSpace' d → ℂ} : ComplexMeasurable f ↔ RealMeasurable (Complex.re_fun f) ∧ RealMeasurable (Complex.im_fun f) := by sorry

/-- Exercise 1.3.7 -/
theorem RealMeasurable.TFAE {d:ℕ} {f: EuclideanSpace' d → ℝ}:
    [
      RealMeasurable f,
      ∃ (g: ℕ → EuclideanSpace' d → ℝ), (∀ n, RealSimpleFunction (g n)) ∧ (PointwiseAeConvergesTo g f),
      UnsignedMeasurable (EReal.pos_fun f) ∧ UnsignedMeasurable (EReal.neg_fun f),
      ∀ U: Set ℝ, IsOpen U → MeasurableSet (f⁻¹' U),
      ∀ K: Set ℝ, IsClosed K → MeasurableSet (f⁻¹' K)
    ].TFAE
  := by sorry

theorem ComplexMeasurable.TFAE {d:ℕ} {f: EuclideanSpace' d → ℂ}:
    [
      ComplexMeasurable f,
      ∃ (g: ℕ → EuclideanSpace' d → ℂ), (∀ n, ComplexSimpleFunction (g n)) ∧ (PointwiseAeConvergesTo g f),
      RealMeasurable (Complex.re_fun f) ∧ RealMeasurable (Complex.im_fun f),
      UnsignedMeasurable (EReal.pos_fun (Complex.re_fun f)) ∧ UnsignedMeasurable (EReal.neg_fun (Complex.im_fun f)) ∧ UnsignedMeasurable (EReal.pos_fun (Complex.im_fun f)) ∧ UnsignedMeasurable (EReal.neg_fun (Complex.re_fun f)),
      ∀ U: Set ℂ, IsOpen U → MeasurableSet (f⁻¹' U),
      ∀ K: Set ℂ, IsClosed K → MeasurableSet (f⁻¹' K)
    ].TFAE
  := by sorry

/-- Exercise 1.3.8(i) -/
theorem Continuous.RealMeasurable {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: Continuous f) : RealMeasurable f := by sorry

theorem Continuous.ComplexMeasurable {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: Continuous f) : ComplexMeasurable f := by sorry

/-- Exercise 1.3.8(ii) -/
theorem UnsignedSimpleFunction.iff' {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: Unsigned f) : UnsignedSimpleFunction f ↔ UnsignedMeasurable f ∧ Finite (f '' Set.univ) := by sorry

/-- Exercise 1.3.8(iii) -/
theorem RealMeasurable.aeEqual {d:ℕ} {f g: EuclideanSpace' d → ℝ} (hf: RealMeasurable f) (heq: AlmostEverywhereEqual f g) : RealMeasurable g := by sorry

theorem ComplexMeasurable.aeEqual {d:ℕ} {f g: EuclideanSpace' d → ℂ} (hf: ComplexMeasurable f) (heq: AlmostEverywhereEqual f g) : ComplexMeasurable g := by sorry

/-- Exercise 1.3.8(iv) -/
theorem RealMeasurable.aeLimit {d:ℕ} {f: EuclideanSpace' d → ℝ} (g: ℕ → EuclideanSpace' d → ℝ) (hf: ∀ n, RealMeasurable (g n)) (heq: PointwiseAeConvergesTo g f) : RealMeasurable f := by sorry

theorem ComplexMeasurable.aeLimit {d:ℕ} {f: EuclideanSpace' d → ℂ} (g: ℕ → EuclideanSpace' d → ℂ) (hf: ∀ n, ComplexMeasurable (g n)) (heq: PointwiseAeConvergesTo g f) : ComplexMeasurable f := by sorry

/-- Exercise 1.3.8(v) -/
theorem RealMeasurable.comp_cts {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealMeasurable f) {φ: ℝ → ℝ} (hφ: Continuous φ)  : RealMeasurable (φ ∘ f) := by sorry

theorem ComplexMeasurable.comp_cts {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexMeasurable f) {φ: ℂ → ℂ} (hφ: Continuous φ)  : ComplexMeasurable (φ ∘ f) := by sorry

/-- Exercise 1.3.8(vi) -/
theorem RealMeasurable.add {d:ℕ} {f g: EuclideanSpace' d → ℝ} (hf: RealMeasurable f) (hg: RealMeasurable g) : RealMeasurable (f + g) := by sorry

theorem ComplexMeasurable.add {d:ℕ} {f g: EuclideanSpace' d → ℂ} (hf: ComplexMeasurable f) (hg: ComplexMeasurable g) : ComplexMeasurable (f + g) := by sorry

/-- Exercise 1.3.8(vi) -/
theorem RealMeasurable.sub {d:ℕ} {f g: EuclideanSpace' d → ℝ} (hf: RealMeasurable f) (hg: RealMeasurable g) : RealMeasurable (f - g) := by sorry

theorem ComplexMeasurable.sub {d:ℕ} {f g: EuclideanSpace' d → ℂ} (hf: ComplexMeasurable f) (hg: ComplexMeasurable g) : ComplexMeasurable (f - g) := by sorry

/-- Exercise 1.3.8(vi) -/
theorem RealMeasurable.mul {d:ℕ} {f g: EuclideanSpace' d → ℝ} (hf: RealMeasurable f) (hg: RealMeasurable g) : RealMeasurable (f * g) := by sorry

theorem ComplexMeasurable.mul {d:ℕ} {f g: EuclideanSpace' d → ℂ} (hf: ComplexMeasurable f) (hg: ComplexMeasurable g) : ComplexMeasurable (f * g) := by sorry


open Classical in
/-- Exercise 1.3.9 -/
theorem RealMeasurable.riemann_integrable {f: ℝ → ℝ} {I: BoundedInterval} (hf: RiemannIntegrableOn f I) : RealMeasurable ((fun x ↦ if x ∈ I.toSet then f x else 0) ∘ EuclideanSpace'.equiv_Real) := by sorry
