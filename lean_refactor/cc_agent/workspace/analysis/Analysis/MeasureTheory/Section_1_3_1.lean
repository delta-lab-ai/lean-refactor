import Analysis.MeasureTheory.Section_1_2_3

/-!
# Introduction to Measure Theory, Section 1.3.1: Integration of simple functions

A companion to (the introduction to) Section 1.3.1 of the book "An introduction to Measure Theory".

-/

-- some tools to convert between EReal-valued, ℝ-valued, and ℂ-valued functions

def EReal.abs_fun {X Y:Type*} [RCLike Y] (f: X → Y) : X → EReal := fun x ↦ ‖f x‖.toEReal
def Complex.re_fun {X:Type*} (f: X → ℂ) : X → ℝ := fun x ↦ Complex.re (f x)
def Complex.im_fun {X:Type*} (f: X → ℂ) : X → ℝ := fun x ↦ Complex.im (f x)
def Complex.conj_fun {X:Type*} (f: X → ℂ) : X → ℂ := fun x ↦ starRingEnd ℂ (f x)
def EReal.pos_fun {X:Type*} (f: X → ℝ) : X → EReal := fun x ↦ (max (f x) 0).toEReal
def EReal.neg_fun {X:Type*} (f: X → ℝ) : X → EReal := fun x ↦ (max (-f x) 0).toEReal
def Real.complex_fun {X:Type*} (f: X → ℝ) : X → ℂ := fun x ↦ Complex.ofReal (f x)
def Real.EReal_fun {X:Type*} (f: X → ℝ) : X → EReal := fun x ↦ Real.toEReal (f x)

noncomputable def EReal.indicator {X:Type*} (A: Set X) : X → EReal := Real.EReal_fun A.indicator'
noncomputable def Complex.indicator {X:Type*} (A: Set X) : X → ℂ := Real.complex_fun A.indicator'

/-- Definition 1.3.2 -/
def UnsignedSimpleFunction {d:ℕ} (f: EuclideanSpace' d → EReal) : Prop := ∃ (k:ℕ) (c: Fin k → EReal) (E: Fin k → Set (EuclideanSpace' d)),
  (∀ i, LebesgueMeasurable (E i) ∧ c i ≥ 0) ∧ f = ∑ i, (c i) • (EReal.indicator (E i))

def RealSimpleFunction {d:ℕ} (f: EuclideanSpace' d → ℝ) : Prop := ∃ (k:ℕ) (c: Fin k → ℝ) (E: Fin k → Set (EuclideanSpace' d)),
  (∀ i, LebesgueMeasurable (E i)) ∧ f = ∑ i, (c i) • (E i).indicator'

def ComplexSimpleFunction {d:ℕ} (f: EuclideanSpace' d → ℂ) : Prop := ∃ (k:ℕ) (c: Fin k → ℝ) (E: Fin k → Set (EuclideanSpace' d)),
  (∀ i, LebesgueMeasurable (E i)) ∧ f = ∑ i, (c i) • (Complex.indicator (E i))

-- TODO: coercions between these concepts, and vector space structure on real and complex simple functions (and cone structure on unsigned simple functions).


@[coe]
abbrev RealSimpleFunction.toComplex {d:ℕ} (f: EuclideanSpace' d → ℝ) (df: RealSimpleFunction f) : ComplexSimpleFunction (Real.complex_fun f) := by sorry

instance RealSimpleFunction.coe_complex {d:ℕ} (f: EuclideanSpace' d → ℝ) : Coe (RealSimpleFunction f) (ComplexSimpleFunction (Real.complex_fun f)) := {
  coe := RealSimpleFunction.toComplex f
}


lemma UnsignedSimpleFunction.add {d:ℕ} {f g: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) (hg: UnsignedSimpleFunction g) : UnsignedSimpleFunction (f + g) := by
  sorry

lemma UnsignedSimpleFunction.smul {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) {a: EReal} (ha: a ≥ 0) : UnsignedSimpleFunction (a • f) := by
  sorry

lemma RealSimpleFunction.add {d:ℕ} {f g: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) (hg: RealSimpleFunction g) : RealSimpleFunction (f + g) := by
  sorry

lemma ComplexSimpleFunction.add {d:ℕ} {f g: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) (hg: ComplexSimpleFunction g) : ComplexSimpleFunction (f + g) := by
  sorry

lemma RealSimpleFunction.smul {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) (a: ℝ)  : RealSimpleFunction (a • f) := by
  sorry

lemma ComplexSimpleFunction.smul {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) (a: ℂ)  : ComplexSimpleFunction (a • f) := by
  sorry

lemma ComplexSimpleFunction.conj {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) : ComplexSimpleFunction (Complex.conj_fun f) := by
  sorry

noncomputable def UnsignedSimpleFunction.integ {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) : EReal := ∑ i, (hf.choose_spec.choose i) * Lebesgue_measure (hf.choose_spec.choose_spec.choose i)

/-- Lemma 1.3.4 (Well-definedness of simple integral) -/
lemma UnsignedSimpleFunction.integral_eq {d:ℕ} {f: EuclideanSpace' d → EReal} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) {k:ℕ} {c: Fin k → EReal}
{E: Fin k → Set (EuclideanSpace' d)} (hmes: ∀ i, LebesgueMeasurable (E i)) (hnonneg: ∀ i, c i ≥ 0) (heq: f = ∑ i, (c i) • (EReal.indicator (E i))) :
 hf.integ =  ∑ i, (hf.choose_spec.choose i) * Lebesgue_measure (hf.choose_spec.choose_spec.choose i) := by sorry

/-- Definition 1.3.5 -/
def AlmostAlways {d:ℕ} (P: EuclideanSpace' d → Prop) : Prop :=
  IsNull { x | ¬ P x }

/-- Definition 1.3.5 -/
def AlmostEverywhereEqual {d:ℕ} {X: Type*} (f g: EuclideanSpace' d → X) : Prop :=
  AlmostAlways (fun x ↦ f x = g x)

/-- Definition 1.3.5 -/
def Support {X Y: Type*} [Zero Y] (f: X → Y) : Set X := { x | f x ≠ 0 }

lemma UnsignedSimpleFunction.support_measurable {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) : LebesgueMeasurable (Support f) := by
  sorry

lemma AlmostAlways.ofAlways {d:ℕ} {P: EuclideanSpace' d → Prop} (h: ∀ x, P x) : AlmostAlways P := by
  sorry

lemma AlmostAlways.mp {d:ℕ} {P Q: EuclideanSpace' d → Prop} (hP: AlmostAlways P) (himp: ∀ x, P x → Q x) : AlmostAlways Q := by
  sorry

lemma AlmostAlways.countable {d:ℕ} {I: Type*} [Countable I] {P: I → EuclideanSpace' d → Prop} (hP: ∀ i, AlmostAlways (P i)) : AlmostAlways (fun x ↦ ∀ i, P i x) := by
  sorry

-- TODO: AlmostEverywhereEqual is an Equiv

/-- Exercise 1.3.1 (i) (Unsigned linearity) -/
lemma UnsignedSimpleFunction.integral_add {d:ℕ} {f g: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) (hg: UnsignedSimpleFunction g) :
  (hf.add hg).integ = hf.integ + hg.integ := by
  sorry

/-- Exercise 1.3.1 (i) (Unsigned linearity) -/
lemma UnsignedSimpleFunction.integral_smul {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) {c:EReal} (hc: c ≥ 0) :
  (hf.smul hc).integ = c * hf.integ := by
  sorry

/-- Exercise 1.3.1 (ii) (Finiteness) -/
lemma UnsignedSimpleFunction.integral_finite_iff {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) :
  (hf.integ < ⊤) ↔ (AlmostAlways (fun x ↦ f x < ⊤)) ∧ (Lebesgue_measure (Support f)) < ⊤ := by
  sorry

/-- Exercise 1.3.1 (iii) (Vanishing) -/
lemma UnsignedSimpleFunction.integral_eq_zero_iff {d:ℕ} {f: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) :
  (hf.integ = 0) ↔ AlmostAlways (fun x ↦ f x = 0) := by
  sorry

/-- Exercise 1.3.1 (iv) (Equivalence) -/
lemma UnsignedSimpleFunction.integral_eq_integral_of_aeEqual {d:ℕ} {f g: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) (hg: UnsignedSimpleFunction g)
  (hae: AlmostEverywhereEqual f g) :
  hf.integ = hg.integ := by
  sorry

/-- Exercise 1.3.1 (v) (Monotonicity) -/
lemma UnsignedSimpleFunction.integral_le_integral_of_aeLe {d:ℕ} {f g: EuclideanSpace' d → EReal} (hf: UnsignedSimpleFunction f) (hg: UnsignedSimpleFunction g)
  (hae: AlmostAlways (fun x ↦ f x ≤ g x)) :
  hf.integ ≤ hg.integ := by
  sorry

/-- Exercise 1.3.1(vi) (Compatibility with Lebesgue measure) -/
lemma UnsignedSimpleFunction.indicator {d:ℕ} {E: Set (EuclideanSpace' d)} (hE: LebesgueMeasurable E) :
  UnsignedSimpleFunction (Real.toEReal ∘ E.indicator') := by
  sorry

/-- Exercise 1.3.1(vi) (Compatibility with Lebesgue measure) -/
lemma UnsignedSimpleFunction.integral_indicator {d:ℕ} {E: Set (EuclideanSpace' d)} (hE: LebesgueMeasurable E) :
  (UnsignedSimpleFunction.indicator hE).integ = Lebesgue_measure E := by
  sorry

lemma RealSimpleFunction.abs {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) : UnsignedSimpleFunction (EReal.abs_fun f) := by
  sorry

lemma ComplexSimpleFunction.abs {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) : UnsignedSimpleFunction (EReal.abs_fun f) := by
  sorry

/-- Definition 1.3.6 (Absolutely convergent simple integral) -/
def RealSimpleFunction.AbsolutelyIntegrable {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) : Prop :=
  (hf.abs).integ < ⊤

/-- Definition 1.3.6 (Absolutely convergent simple integral) -/
def ComplexSimpleFunction.AbsolutelyIntegrable {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) : Prop :=
  (hf.abs).integ < ⊤

def RealSimpleFunction.pos {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) : UnsignedSimpleFunction (EReal.pos_fun f) := by sorry

def RealSimpleFunction.neg {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) : UnsignedSimpleFunction (EReal.neg_fun f) := by sorry

noncomputable def RealSimpleFunction.integ {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) : ℝ := (hf.pos).integ.toReal - (hf.neg).integ.toReal

def ComplexSimpleFunction.re {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) : RealSimpleFunction (Complex.re_fun f) := by sorry

def ComplexSimpleFunction.im {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) : RealSimpleFunction (Complex.im_fun f) := by sorry

noncomputable def ComplexSimpleFunction.integ {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) : ℂ :=
  hf.re.integ + Complex.I * hf.im.integ

lemma RealSimpleFunction.absolutelyIntegrable_iff {d:ℕ} {f: EuclideanSpace' d → ℝ} (hf: RealSimpleFunction f) : hf.AbsolutelyIntegrable ↔ Lebesgue_measure (Support f) < ⊤ := by
  sorry

lemma ComplexSimpleFunction.absolutelyIntegrable_iff {d:ℕ} {f: EuclideanSpace' d → ℂ} (hf: ComplexSimpleFunction f) : hf.AbsolutelyIntegrable ↔ Lebesgue_measure (Support f) < ⊤ := by
  sorry

lemma RealSimpleFunction.AbsolutelyIntegrable.add {d:ℕ} {f g: EuclideanSpace' d → ℝ} {hf: RealSimpleFunction f} {hg: RealSimpleFunction g} (hf_integ: hf.AbsolutelyIntegrable) (hg_integ: hg.AbsolutelyIntegrable) :
  (hf.add hg).AbsolutelyIntegrable := by sorry

lemma ComplexSimpleFunction.AbsolutelyIntegrable.add {d:ℕ} {f g: EuclideanSpace' d → ℂ} {hf: ComplexSimpleFunction f} {hg: ComplexSimpleFunction g} (hf_integ: hf.AbsolutelyIntegrable) (hg_integ: hg.AbsolutelyIntegrable) :
  (hf.add hg).AbsolutelyIntegrable := by sorry

lemma RealSimpleFunction.AbsolutelyIntegrable.smul {d:ℕ} {f: EuclideanSpace' d → ℝ} {hf: RealSimpleFunction f} (hf_integ: hf.AbsolutelyIntegrable) (a: ℝ) :
  (hf.smul a).AbsolutelyIntegrable := by sorry

lemma ComplexSimpleFunction.AbsolutelyIntegrable.smul {d:ℕ} {f: EuclideanSpace' d → ℂ} {hf: ComplexSimpleFunction f} (hf_integ: hf.AbsolutelyIntegrable) (a: ℂ) :
  (hf.smul a).AbsolutelyIntegrable := by sorry

lemma ComplexSimpleFunction.AbsolutelyIntegrable.conj {d:ℕ} {f: EuclideanSpace' d → ℂ} {hf: ComplexSimpleFunction f} (hf_integ: hf.AbsolutelyIntegrable) :
  (hf.conj).AbsolutelyIntegrable := by sorry

/-- Exercise 1.3.2 (i) (*-linearity) -/
lemma RealSimpleFunction.integ_add {d:ℕ} {f g: EuclideanSpace' d → ℝ} {hf: RealSimpleFunction f} {hg: RealSimpleFunction g} (hf_integ: hf.AbsolutelyIntegrable) (hg_integ: hg.AbsolutelyIntegrable) : (hf.add hg).integ = hf.integ + hg.integ := by sorry

lemma ComplexSimpleFunction.integ_add {d:ℕ} {f g: EuclideanSpace' d → ℂ} {hf: ComplexSimpleFunction f} {hg: ComplexSimpleFunction g} (hf_integ: hf.AbsolutelyIntegrable) (hg_integ: hg.AbsolutelyIntegrable) : (hf.add hg).integ = hf.integ + hg.integ := by
  sorry

/-- Exercise 1.3.2 (i) (*-linearity) -/
lemma RealSimpleFunction.integ_smul {d:ℕ} {f: EuclideanSpace' d → ℝ} {hf: RealSimpleFunction f} (hf_integ: hf.AbsolutelyIntegrable) (a: ℝ) : (hf.smul a).integ = a * hf.integ := by
  sorry

lemma ComplexSimpleFunction.integ_smul {d:ℕ} {f: EuclideanSpace' d → ℂ} {hf: ComplexSimpleFunction f} (hf_integ: hf.AbsolutelyIntegrable) (a: ℂ) : (hf.smul a).integ = a * hf.integ := by
  sorry

/-- Exercise 1.3.2 (i) (*-linearity) -/
lemma ComplexSimpleFunction.integral_conj {d:ℕ} {f: EuclideanSpace' d → ℂ} {hf: ComplexSimpleFunction f} (hf_integ: hf.AbsolutelyIntegrable) : (hf.conj).integ = (starRingEnd ℂ) hf.integ := by
  sorry

/-- Exercise 1.3.2 (ii) (equivalence) -/
lemma RealSimpleFunction.integral_eq_integral_of_aeEqual {d:ℕ} {f g: EuclideanSpace' d → ℝ} {hf: RealSimpleFunction f} {hg: RealSimpleFunction g} (hf_integ: hf.AbsolutelyIntegrable) (hg_integ: hg.AbsolutelyIntegrable) (h_ae: AlmostEverywhereEqual f g) : hf.integ = hg.integ := by
  sorry

lemma ComplexSimpleFunction.integral_eq_integral_of_aeEqual {d:ℕ} {f g: EuclideanSpace' d → ℂ} {hf: ComplexSimpleFunction f} {hg: ComplexSimpleFunction g} (hf_integ: hf.AbsolutelyIntegrable) (hg_integ: hg.AbsolutelyIntegrable) (h_ae: AlmostEverywhereEqual f g) : hf.integ = hg.integ := by
  sorry

/-- Exercise 1.3.2(iii) (Compatibility with Lebesgue measure) -/
lemma RealSimpleFunction.indicator {d:ℕ} {E: Set (EuclideanSpace' d)} (hE: LebesgueMeasurable E) :
  RealSimpleFunction (E.indicator') := by
  sorry

lemma ComplexSimpleFunction.indicator {d:ℕ} {E: Set (EuclideanSpace' d)} (hE: LebesgueMeasurable E) :
  ComplexSimpleFunction (Complex.indicator E) := by
  sorry

/-- Exercise 1.3.2(iii) (Compatibility with Lebesgue measure) -/
lemma RealSimpleFunction.integral_indicator {d:ℕ} {E: Set (EuclideanSpace' d)} (hE: LebesgueMeasurable E) (hfin: Lebesgue_measure E < ⊤): (RealSimpleFunction.indicator hE).integ = (Lebesgue_measure E).toReal := by
  sorry

lemma ComplexSimpleFunction.integral_indicator {d:ℕ} {E: Set (EuclideanSpace' d)} (hE: LebesgueMeasurable E) (hfin: Lebesgue_measure E < ⊤): (ComplexSimpleFunction.indicator hE).integ = (Lebesgue_measure E).toReal := by
  sorry
