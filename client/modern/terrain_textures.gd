extends RefCounted
const Assets = preload("res://original_assets.gd")
const PERMUTATION := [0, 1, 3, 2, 5, 10, 4, 12, 8, 14, 13, 11, 7, 9, 6, 15]
var error := ""
var _mips: Dictionary = {}
var _masks: Dictionary = {}

func _levels(image: Image) -> Array[Image]:
	var result: Array[Image] = []
	var data := image.get_data()
	var offset := 0
	for level in image.get_mipmap_count() + 1:
		var size := image.get_size() / (1 << level)
		var count := size.x * size.y * 4
		result.append(Image.create_from_data(size.x, size.y, false, Image.FORMAT_RGBA8, data.slice(offset, offset + count)))
		offset += count
	return result

func _family(name: String) -> String:
	var lower := name.to_lower()
	return lower.left(-3) if lower.length() > 3 and lower.right(3).is_valid_int() else ""

func _mask(bank: int, coverage: int, assets: Assets) -> Array:
	var key := "%d/%d" % [bank, coverage]
	if _masks.has(key):
		return _masks[key]
	var source := PackedByteArray()
	if coverage in [0, 15]:
		source.resize(21845)
		source.fill(255 if coverage == 15 else 0)
	else:
		var raw := assets._read("base", "%dtemplate%03d" % [bank, PERMUTATION.find(coverage)])
		if raw.size() != 21848 or raw[0] != 3 or raw.decode_u16(1) != 7:
			error = "Invalid original terrain mask: " + key
			return []
		source = raw.slice(3)
	var result: Array[Image] = []
	var offset := 0
	for level in 8:
		var size := 128 >> level
		var pixels := PackedByteArray()
		pixels.resize(size * size * 2)
		for index in size * size:
			var value: int = source[offset + index]
			if value not in [0, 255]:
				error = "Nonbinary original terrain mask: " + key
				return []
			pixels[index * 2] = 255
			pixels[index * 2 + 1] = value
		result.append(Image.create_from_data(size, size, false, Image.FORMAT_LA8, pixels))
		offset += size * size
	_masks[key] = result
	return result

func compose(recipe: String, assets: Assets) -> Dictionary:
	var tokens := recipe.strip_edges().trim_prefix("+").split(" ", false)
	var mixed := recipe.begins_with("+")
	var count := tokens.size() / 3 if mixed else 1
	if count < 1 or count > 4 or (mixed and tokens.size() % 3 != 0):
		error = "Unsupported original terrain recipe."
		return {}
	var layers: Array = []
	var base := 0
	var found_family := false
	var bank := 1
	for slot in int(count):
		var name: String = tokens[slot * 3 + 1] if mixed else tokens[0]
		var lower := name.to_lower()
		var archive := "landscape" if assets._names.landscape.has(lower) else "base" if assets._names.base.has(lower) else "res_640x480"
		var bitmap := assets.texture(name, archive)
		if bitmap == null:
			error = "Missing original terrain bitmap: " + name
			return {}
		var key := archive + "/" + lower
		var original: Image = assets.image_cache[key]
		if original.get_size() != Vector2i(128, 128) or original.get_mipmap_count() != 7:
			if count == 1:
				return {"special": assets.material(name, archive)}
			error = "Unsupported mixed bitmap dimensions: " + name
			return {}
		if not _mips.has(key):
			_mips[key] = _levels(original)
		var coverage := 15
		if mixed:
			var value: String = tokens[slot * 3 + 2]
			if not value.is_valid_int() or int(value) < 0 or int(value) > 15:
				error = "Invalid original terrain coverage."
				return {}
			coverage = 15 ^ int(value)
		layers.append({"image": original, "levels": _mips[key], "coverage": coverage})
		# Retail 0x49cc50 chooses the first highest-priority registered family.
		# The recovered registry gives every family priority 1, with a per-family
		# mask bank. Unknown standalone bitmap names do not outrank a family.
		var family := _family(name)
		if not found_family and FAMILY_BANKS.has(family):
			base = slot
			bank = FAMILY_BANKS[family]
			found_family = true
	if count == 1:
		return {"image": layers[0].image}
	var masks: Array = []
	for slot in layers.size():
		masks.append([] if slot == base else _mask(bank, layers[slot].coverage, assets))
		if slot != base and masks[slot].is_empty():
			return {}
	var pixels := PackedByteArray()
	for level in 8:
		var target: Image = layers[base].levels[level].duplicate()
		for slot in layers.size():
			if slot != base:
				target.blit_rect_mask(layers[slot].levels[level], masks[slot][level], Rect2i(Vector2i.ZERO, target.get_size()), Vector2i.ZERO)
		pixels.append_array(target.get_data())
	return {"image": Image.create_from_data(128, 128, true, Image.FORMAT_RGBA8, pixels)}

## Original retail terrain family registry (0x49cf20), before map composition.
const FAMILY_BANKS := {
    "10martian": 1,
    "11ice": 1,
    "11martian": 1,
    "12martian": 1,
    "13martian": 1,
    "14martian": 1,
    "19bush": 3,
    "1bush": 1,
    "1granite": 1,
    "1ice": 1,
    "1martian": 1,
    "1silt": 1,
    "1snow": 1,
    "20bush": 2,
    "20bush_4sand": 1,
    "2gbdirt": 1,
    "2grandcan": 1,
    "2marsand": 1,
    "2marsbark": 1,
    "2marscanyon": 1,
    "2marsdino": 1,
    "2marsdirt": 1,
    "2marsfunk": 1,
    "2marsland": 1,
    "2marslava": 1,
    "2marsold": 1,
    "2marsrock": 1,
    "2marsrough": 1,
    "2marssoil": 1,
    "2marsstucco": 1,
    "2marsvolc": 1,
    "2marswirl": 1,
    "2martian": 1,
    "2rough": 1,
    "2snow": 1,
    "3bush": 2,
    "3grass": 1,
    "3litegrass": 1,
    "3martian": 1,
    "4granite": 2,
    "4martian": 1,
    "4rough.": 1,
    "4sand": 1,
    "4snow": 4,
    "5granite": 1,
    "5granitebrown": 1,
    "5ice": 3,
    "6martian": 1,
    "6redcanyon": 2,
    "6redrockwall": 2,
    "7martian": 1,
    "8ice": 1,
    "8martian": 1,
    "9bush": 2,
    "9bush_1silt": 1,
    "9martian": 1,
    "bdt": 1,
    "bdtdark": 1,
    "bluegranite": 1,
    "brownmud": 4,
    "canyon": 2,
    "darkrock": 2,
    "gbdirt": 1,
    "gbdirt_grassy": 1,
    "gbdirt_rocky": 1,
    "gdt": 1,
    "gmd": 4,
    "grandcan": 1,
    "greenmartian": 1,
    "greenrock": 2,
    "groundmetal": 1,
    "groundrunway": 1,
    "groundstruct": 1,
    "grs": 1,
    "jjcanyon": 2,
    "junglecanyon": 2,
    "machuwall_b": 3,
    "machuwall_f": 3,
    "machuwall_l": 3,
    "machuwall_r": 3,
    "marsand": 1,
    "marsbark": 1,
    "marscanyon": 1,
    "marsdino": 1,
    "marsdirt": 1,
    "marsfunk": 1,
    "marsland": 1,
    "marslava": 1,
    "marsold": 1,
    "marsrock": 1,
    "marsrough": 1,
    "marssoil": 1,
    "marsstucco": 1,
    "marsvolc": 1,
    "marswirl": 1,
    "megadirt": 3,
    "olivesage": 2,
    "reddirt": 3,
    "redgranite": 1,
    "rockwall": 2,
    "roman": 1,
    "romanfloor": 3,
    "sandrock": 2,
    "stonepath": 4,
    "udgreekwall": 3,
    "ulgreekwall": 3,
    "wheat": 2,
    "yellowmartian": 1,
}
