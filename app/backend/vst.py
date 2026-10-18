"""VST maker for the Modern-TK80 mini DAW.

Generates simple VST3-compatible plugin source skeletons (instrument or effect)
that can be compiled with the VST3 SDK or a JUCE project. This is a starter
generator, not a full compiler. Output is a C++ source file and a short
build note.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

VST_DIR = Path(os.environ.get("TK80_VST", "uploads/vst"))
VST_DIR.mkdir(parents=True, exist_ok=True)

PLUGIN_TYPES = ("instrument", "effect")


def make_vst(
    name: str,
    plugin_type: str = "instrument",
    channels: int = 2,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write a VST3 skeleton and return its path and notes.

    plugin_type: "instrument" or "effect".
    params: optional dict of parameter names to default values (float).
    """
    if plugin_type not in PLUGIN_TYPES:
        raise ValueError(f"plugin_type must be one of {PLUGIN_TYPES}")
    safe_name = "".join(c if c.isalnum() else "_" for c in name) or "Plugin"
    params = params or {}
    if plugin_type == "instrument" and "gain" not in params:
        params["gain"] = 0.8
    if plugin_type == "effect" and "mix" not in params:
        params["mix"] = 1.0

    source = _render_skeleton(safe_name, plugin_type, channels, params)
    dest = VST_DIR / f"{safe_name}.cpp"
    if dest.exists():
        i = 1
        while dest.exists():
            dest = VST_DIR / f"{safe_name}_{i}.cpp"
            i += 1
    dest.write_text(source, encoding="utf-8")

    note = (
        f"VST3 skeleton written to {dest}. "
        "Compile with the Steinberg VST3 SDK or drop into a JUCE AudioPlugin project. "
        "This is a starter template; process() is a pass-through with a simple gain/mix."
    )
    return {
        "name": safe_name,
        "type": plugin_type,
        "path": str(dest),
        "channels": channels,
        "params": params,
        "note": note,
    }


def _render_skeleton(
    name: str,
    plugin_type: str,
    channels: int,
    params: Dict[str, Any],
) -> str:
    is_instrument = plugin_type == "instrument"
    param_lines = []
    for pname, default in params.items():
        param_lines.append(f'    addParameter(std::make_unique<AudioParameterFloat>("{pname}", "{pname}", 0.0f, 1.0f, {float(default)}f));')
    params_code = "\n".join(param_lines) if param_lines else "    // no parameters"

    process_body = """
        auto* gain = parameters.getRawParameterValue("gain");
        float g = gain ? *gain : 1.0f;
        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
            buffer.applyGain(ch, 0, buffer.getNumSamples(), g);
""" if is_instrument else """
        auto* mix = parameters.getRawParameterValue("mix");
        float m = mix ? *mix : 1.0f;
        buffer.applyGain(m);
"""

    return f'''// Modern-TK80 generated VST3 skeleton: {name}
// Type: {plugin_type} | Channels: {channels}
// Compile with VST3 SDK or JUCE. process() is a starter.

#include <JuceHeader.h>

class {name}Processor : public juce::AudioProcessor
{{
public:
    {name}Processor()
        : AudioProcessor(BusesProperties()
            .withInput("Input", juce::AudioChannelSet::stereo(), true)
            .withOutput("Output", juce::AudioChannelSet::stereo(), true))
    {{
{params_code}
    }}

    void prepareToPlay(double sampleRate, int samplesPerBlock) override {{}}
    void releaseResources() override {{}}

    void processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) override
    {{
        juce::ScopedNoDenormals noDenormals;
        buffer.clear();
{process_body}
        // TODO: implement real DSP or MIDI note handling for instruments
    }}

    juce::AudioProcessorEditor* createEditor() override {{ return nullptr; }}
    bool hasEditor() const override {{ return false; }}

    const juce::String getName() const override {{ return "{name}"; }}
    bool acceptsMidi() const override {{ return {str(is_instrument).lower()}; }}
    bool producesMidi() const override {{ return false; }}
    bool isMidiEffect() const override {{ return false; }}
    double getTailLengthSeconds() const override {{ return 0.0; }}

    int getNumPrograms() override {{ return 1; }}
    int getCurrentProgram() override {{ return 0; }}
    void setCurrentProgram(int) override {{}}
    const juce::String getProgramName(int) override {{ return {{}}; }}
    void changeProgramName(int, const juce::String&) override {{}}

    void getStateInformation(juce::MemoryBlock&) override {{}}
    void setStateInformation(const void*, int) override {{}}

private:
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR({name}Processor)
}};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{{
    return new {name}Processor();
}}
'''
"""
file_path="/workspace/artifacts/Modern-TK80-Inference/app/backend/vst.py"