import pathlib
p = pathlib.Path("synlab/fracture/implicit/field.py")
s = p.read_text(encoding="utf-8")
s = s.replace('''    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi``: the object ``MorphologyHeightField`` expects in its modulation slot."""
        return self.mask(u, v)''',
'''    def value(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """``phi``: the object ``MorphologyHeightField`` expects in its modulation slot."""
        return self.mask(u, v)

    def is_exactly_one(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Duck-type of ``cut.BandWindow``: the footprint core (where the relief is untouched).

        ``surface_features.measure_cutter_surface`` restricts its samples with this method, so the
        implicit envelope can be passed where the frozen band window is expected.
        """
        return self.mask(u, v) >= 1.0 - 1.0e-9''')
p.write_text(s, encoding="utf-8")
print("is_exactly_one added")
