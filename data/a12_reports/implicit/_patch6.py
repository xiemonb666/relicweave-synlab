import pathlib
p = pathlib.Path("synlab/fracture/implicit/field.py")
s = p.read_text(encoding="utf-8")
s = s.replace('''    band = np.abs(signed) <= (2.0 * float(width_mm) + 8.0 * float(step_mm))
    signed_smooth = _masked_blur(signed, band, sigma=float(sigma_cells))''',
'''    band = np.abs(signed) <= (2.0 * float(width_mm) + 8.0 * float(step_mm))
    #: outside the band the blurred value is meaningless (the normalised blur returns 0 there, which
    #: would make the taper 1 *far* outside the footprint and fill the flat frame with relief --
    #: measured as a 0.9 mm interpolation error), so the raw distance is kept there, pushed out of
    #: the taper's range on both sides.
    filled = np.where(signed > 0.0, np.maximum(signed, 2.0 * float(width_mm)),
                      np.minimum(signed, -2.0 * float(width_mm)))
    signed_smooth = np.where(band, _masked_blur(signed, band, sigma=float(sigma_cells)), filled)''')
p.write_text(s, encoding="utf-8")
print("ok")
