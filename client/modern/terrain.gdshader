shader_type spatial;
render_mode unshaded;
uniform sampler2DArray original_tiles : source_color, filter_linear_mipmap, repeat_enable;
varying flat float layer;
void vertex() {
	layer = CUSTOM0.x;
}
void fragment() {
	// Original binary-mask composition has already happened at every stored
	// mip level. Filter the completed bitmap, not its independent ingredients.
	ALBEDO = texture(original_tiles, vec3(UV, layer)).rgb;
}
