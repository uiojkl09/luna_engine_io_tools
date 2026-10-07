# Luna Engine IO Tools

**Luna Engine IO Tools** is a Blender add-on written in Python for working with Luna Engine model and animation assets. It focuses on importing and exporting `.model` files and `.animclip` animation clips directly inside Blender, giving modders and reverse-engineering researchers a cleaner workflow for editing game assets.

## Features

* **Model import**: Import one or more compiled `.model` files into Blender.
* **Model export**: Export selected Blender model data back into the Luna Engine model format.
* **Morph2 editing**: Import model Morph2 data as shape keys, share controls across subsets, and rebuild Morph2 on export.
* **Ziva replacement tools**: Evaluate compiled Ziva2 rigs, transfer named channels to replacement topology, and capture joint-driven poses as editable Morph2 targets.
* **Animation import**: Import `.animclip` files and apply them to an existing armature or camera.
* **Animation export**: Export the selected armature or camera animation as an `.animclip` file.
* **Bone scale animation**: Preserve constant and animated bone scale, including native segment scale compensation.
* **Shape-key animation**: Export keyframed shape-key values as native morph-weight tracks alongside skeletal animation, and import those tracks back onto matching model targets.
* **Camera animation support**: Work with camera clips as well as skeletal animation clips.
* **Blender UI integration**: Adds Luna Engine import/export entries to Blender's File menu and provides panels, properties, and operators for model and animation settings.
* **Pure Python add-on**: Runs inside Blender's bundled Python environment with no extra Python packages required.

## Installation

1. Download or clone this repository.
2. Keep the files inside a folder named `luna_engine_io_tools`, or package that folder as a zip.
3. Open Blender 5.0 or newer.
4. Go to **Edit > Preferences > Add-ons**.
5. Click **Install** and select the zip or folder.
6. Enable **Luna Engine IO Tools** in the add-on list.

You can also copy the `luna_engine_io_tools` folder into Blender's add-ons directory and enable it from the Add-ons panel.

## Usage

### Importing models

1. Go to **File > Import > Luna Engine Model**.
2. Select one or more `.model` files.
3. Enable **Import All LODs** if you want lower-detail subsets too.
4. Keep **Import Shape Keys** enabled when you want to preserve or edit model deformations.
5. Click **Import**.

### Exporting models

1. Select the model/armature hierarchy you want to export.
2. Configure the model export settings in the Luna Engine model panel.
3. Use **File > Export > Luna Engine Model** or the **Export Luna Engine Model** operator.
4. Save the exported `.model` file.

### Importing animations

1. Select the target armature or camera.
2. Go to **File > Import > Luna Engine Anim**.
3. Select one or more `.animclip` files.
4. The importer will apply the clip to the selected compatible object.

### Exporting animations

1. Select an armature with an active action or animated mesh shape keys, or a camera with animation data.
2. Go to **File > Export > Luna Engine Anim**.
3. Set the desired frame range and FPS in the scene/export settings.
4. Export the animation as an `.animclip` file.

### Animating shape keys

Use relative shape keys with **Relative To** set to **Basis**, and keyframe their
**Value** normally. Select the rig and export the AnimClip using the same frame
range and FPS as the bone animation. Export the model too: its Morph2 targets
contain the shape geometry, while the AnimClip contains the weights over time.
The model and animation target names/hashes must match.

Shape keys are detected on meshes parented to the rig or using its Armature
modifier. Shape-key-only clips do not require an active bone action. When
importing, load the matching model with **Import Shape Keys** enabled first.
Morph tracks are recreated as ordinary shape-key actions on the meshes.
Loading another clip replaces previous imported morph actions and resets their
values, including when the new clip has no morph tracks. Authored shape-key
actions are left alone on meshes with no incoming morph tracks.

The exporter supports up to 255 active morph targets and omits all-zero tracks.
Keys sharing an engine target name across meshes must have matching values;
rename keys that should animate independently. Absolute shape keys, custom
relative-key chains, and shape-key vertex-group masks are not supported.
Imported target metadata follows the model exporter's target selection.
Facial phoneme/expression and Ziva animation are separate systems.

Bone scales must be finite and nonnegative. Native segment scale compensation
is preserved through imported joint flags; rigs loaded with an older add-on
can recover those flags from the original model's saved source path. Negative
scale, unsupported shear, and zero parent scale on compensated joints produce
an export error instead of silently changing the animation.

## Supported file types

| Format | Description | Direction |
|---|---|---|
| `.model` | Luna Engine model data, including meshes, subsets, materials, and skeleton data | Import/export |
| `.animclip` | Animation clip data for armatures or cameras | Import/export |

## Requirements

* Blender 5.0.0 or newer.
* Python 3.x, included with Blender.
* No external Python packages required.

## Development

This project is written in pure Python. After editing the add-on, reload it in Blender or restart Blender to test changes. Keep changes focused, test with real assets when possible, and report issues with enough detail to reproduce them.

Animation format tests: `python -m unittest discover -s tests`.
Synthetic Blender round trip:
`blender -b --factory-startup --python tests/blender_animation_roundtrip.py`.
Clip replacement regression:
`blender -b --factory-startup --python tests/blender_morph_clip_replacement.py`.
These tests generate their own data and require no game assets or rendering.

## License

This add-on is licensed under the GNU General Public License v3.0. See the [`LICENSE`](LICENSE) file for full details.

## Disclaimer

This project is not affiliated with Insomniac Games.
