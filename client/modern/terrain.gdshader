shader_type spatial;
render_mode unshaded;
uniform sampler2DArray original_tiles : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2DArray original_masks : filter_nearest_mipmap, repeat_enable;
varying flat vec4 layers;
varying flat vec4 masks;
void vertex() {
	layers = CUSTOM0;
	masks = CUSTOM1;
}
void fragment() {
	vec3 colour = texture(original_tiles, vec3(UV, layers.x)).rgb;
	colour = mix(colour, texture(original_tiles, vec3(UV, layers.y)).rgb, texture(original_masks, vec3(UV, masks.y)).r);
	colour = mix(colour, texture(original_tiles, vec3(UV, layers.z)).rgb, texture(original_masks, vec3(UV, masks.z)).r);
	colour = mix(colour, texture(original_tiles, vec3(UV, layers.w)).rgb, texture(original_masks, vec3(UV, masks.w)).r);
	ALBEDO = colour;
}
