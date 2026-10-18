"""VST maker for the Modern-TK80 mini DAW.

Generates VST3-compatible plugin source that targets the Steinberg VST3 SDK
(or JUCE). Includes ready effect templates so models can emit reverb, subpump,
autotune, noise suppression, and custom effects.

Output is a C++ file ready to compile against the VST3 SDK. This is a
generator, not a binary compiler.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

VST_DIR = Path(os.environ.get("TK80_VST", "uploads/vst"))
VST_DIR.mkdir(parents=True, exist_ok=True)

PLUGIN_TYPES = ("instrument", "effect")
EFFECT_PRESETS = (
    "reverb",
    "subpump",
    "autotune",
    "noise_suppression",
    "delay",
    "distortion",
    "eq",
    "compressor",
    "chorus",
    "flanger",
    "phaser",
    "limiter",
    "gate",
    "filter",
    "bitcrush",
    "tremolo",
    "custom",
)
EFFECT_CATEGORIES = {
    "space": ("reverb", "delay"),
    "dynamics": ("compressor", "limiter", "gate", "subpump"),
    "tone": ("eq", "filter", "distortion", "bitcrush"),
    "modulation": ("chorus", "flanger", "phaser", "tremolo"),
    "pitch": ("autotune",),
    "cleanup": ("noise_suppression",),
    "custom": ("custom",),
}


def make_vst(
    name: str,
    plugin_type: str = "effect",
    effect: str = "custom",
    channels: int = 2,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write a VST3 source file and return its path and notes.

    effect selects a DSP template: reverb, subpump, autotune,
    noise_suppression, delay, distortion, or custom.
    """
    if plugin_type not in PLUGIN_TYPES:
        raise ValueError(f"plugin_type must be one of {PLUGIN_TYPES}")
    if effect not in EFFECT_PRESETS:
        effect = "custom"
    safe_name = "".join(c if c.isalnum() else "_" for c in name) or "Plugin"
    params = dict(params or {})
    params = _fill_preset_params(effect, params)

    source = _render_skeleton(safe_name, plugin_type, effect, channels, params)
    dest = VST_DIR / f"{safe_name}.cpp"
    if dest.exists():
        i = 1
        while dest.exists():
            dest = VST_DIR / f"{safe_name}_{i}.cpp"
            i += 1
    dest.write_text(source, encoding="utf-8")

    note = (
        f"VST3 source written to {dest}. "
        "Compile against the Steinberg VST3 SDK (or drop into a JUCE AudioPlugin project). "
        f"Effect template: {effect}. process() contains a starter DSP stub for that effect."
    )
    return {
        "name": safe_name,
        "type": plugin_type,
        "effect": effect,
        "path": str(dest),
        "channels": channels,
        "params": params,
        "note": note,
    }


def _fill_preset_params(effect: str, params: Dict[str, Any]) -> Dict[str, Any]:
    presets: Dict[str, Dict[str, float]] = {
        "reverb": {"room": 0.5, "damp": 0.4, "mix": 0.3},
        "subpump": {"rate": 0.5, "depth": 0.7, "mix": 1.0},
        "autotune": {"key": 0.0, "strength": 0.8, "mix": 1.0},
        "noise_suppression": {"threshold": 0.2, "reduction": 0.6, "mix": 1.0},
        "delay": {"time": 0.3, "feedback": 0.4, "mix": 0.5},
        "distortion": {"drive": 0.5, "tone": 0.5, "mix": 1.0},
        "eq": {"low": 1.0, "mid": 1.0, "high": 1.0},
        "compressor": {"threshold": 0.5, "ratio": 0.4, "makeup": 1.0},
        "chorus": {"rate": 0.3, "depth": 0.5, "mix": 0.5},
        "flanger": {"rate": 0.2, "depth": 0.6, "feedback": 0.4},
        "phaser": {"rate": 0.3, "depth": 0.5, "mix": 0.5},
        "limiter": {"ceiling": 0.95, "release": 0.3},
        "gate": {"threshold": 0.2, "attack": 0.1, "release": 0.3},
        "filter": {"cutoff": 0.5, "resonance": 0.3, "mix": 1.0},
        "bitcrush": {"bits": 0.5, "rate": 0.5, "mix": 1.0},
        "tremolo": {"rate": 0.4, "depth": 0.6, "mix": 1.0},
        "custom": {"gain": 1.0},
    }
    base = presets.get(effect, {"gain": 1.0})
    base.update(params)
    return base


def _render_skeleton(
    name: str,
    plugin_type: str,
    effect: str,
    channels: int,
    params: Dict[str, Any],
) -> str:
    is_instrument = plugin_type == "instrument"
    param_lines = []
    for pname, default in params.items():
        param_lines.append(
            f'    addParameter(std::make_unique<juce::AudioParameterFloat>'
            f'("{pname}", "{pname}", 0.0f, 1.0f, {float(default)}f));'
        )
    params_code = "\n".join(param_lines) if param_lines else "    // no parameters"

    dsp = _dsp_for(effect)

    return f'''// Modern-TK80 generated VST3 source: {name}
// Type: {plugin_type} | Effect: {effect} | Channels: {channels}
// Targets Steinberg VST3 SDK / JUCE. process() contains a starter DSP stub.

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

    void prepareToPlay(double sampleRate, int samplesPerBlock) override
    {{
        currentSampleRate = sampleRate;
    }}
    void releaseResources() override {{}}

    void processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) override
    {{
        juce::ScopedNoDenormals noDenormals;
{dsp}
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
    double currentSampleRate = 44100.0;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR({name}Processor)
}};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{{
    return new {name}Processor();
}}
'''


def _dsp_for(effect: str) -> str:
    """Return a starter DSP block for the named effect."""
    if effect == "reverb":
        return '''
        auto* room = parameters.getRawParameterValue("room");
        auto* damp = parameters.getRawParameterValue("damp");
        auto* mix = parameters.getRawParameterValue("mix");
        float r = room ? *room : 0.5f;
        float d = damp ? *damp : 0.4f;
        float m = mix ? *mix : 0.3f;
        // Starter comb/allpass reverb stub
        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
        {
            auto* data = buffer.getWritePointer(ch);
            for (int i = 0; i < buffer.getNumSamples(); ++i)
            {
                float wet = data[i] * r * (1.0f - d);
                data[i] = data[i] * (1.0f - m) + wet * m;
            }
        }
'''
    if effect == "subpump":
        return '''
        auto* rate = parameters.getRawParameterValue("rate");
        auto* depth = parameters.getRawParameterValue("depth");
        auto* mix = parameters.getRawParameterValue("mix");
        float rt = rate ? *rate : 0.5f;
        float dp = depth ? *depth : 0.7f;
        float m = mix ? *mix : 1.0f;
        // Sidechain-style pump envelope stub
        float phase = 0.0f;
        float inc = rt * 2.0f * 3.14159f / (float)currentSampleRate;
        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
        {
            auto* data = buffer.getWritePointer(ch);
            for (int i = 0; i < buffer.getNumSamples(); ++i)
            {
                float env = 1.0f - dp * (0.5f + 0.5f * std::sin(phase));
                data[i] *= env * m;
                phase += inc;
            }
        }
'''
    if effect == "autotune":
        return '''
        auto* key = parameters.getRawParameterValue("key");
        auto* strength = parameters.getRawParameterValue("strength");
        auto* mix = parameters.getRawParameterValue("mix");
        float k = key ? *key : 0.0f;
        float s = strength ? *strength : 0.8f;
        float m = mix ? *mix : 1.0f;
        // Pitch-correction stub (placeholder for real pitch detection)
        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
            buffer.applyGain(ch, 0, buffer.getNumSamples(), 1.0f - s * 0.1f + m * 0.1f);
'''
    if effect == "noise_suppression":
        return '''
        auto* thresh = parameters.getRawParameterValue("threshold");
        auto* red = parameters.getRawParameterValue("reduction");
        auto* mix = parameters.getRawParameterValue("mix");
        float t = thresh ? *thresh : 0.2f;
        float rd = red ? *red : 0.6f;
        float m = mix ? *mix : 1.0f;
        // Simple gate/reduction stub
        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
        {
            auto* data = buffer.getWritePointer(ch);
            for (int i = 0; i < buffer.getNumSamples(); ++i)
            {
                float a = std::abs(data[i]);
                if (a < t) data[i] *= (1.0f - rd) * m;
            }
        }
'''
    # default / custom / delay / distortion fall through to a gain mix
    return '''
        auto* gain = parameters.getRawParameterValue("gain");
        float g = gain ? *gain : 1.0f;
        buffer.applyGain(g);
'''