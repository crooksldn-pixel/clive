import { useState } from 'react';
import { Pressable, StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import { colour, font, TAP } from '@/theme/tokens';
import { Label, Micro, Mono } from './Type';

export type OptionValue = {
  name: string;
  /** Nothing in any combination is buyable. Not pressable. */
  soldOut: boolean;
  /** Not buyable with what else is chosen, but is in another combination. */
  unavailableHere: boolean;
};

type Props = {
  option: string;
  values: OptionValue[];
  selected: string | undefined;
  onSelect: (value: string) => void;
};

/**
 * One option (Size, Colour, …) as a row of buttons, always labelled with the
 * option's own name — the tee is Colour AND Size, and an unlabelled row of
 * "BLACK WHITE" above "S M L" was one of the things SimGym tripped on.
 */
export function OptionRow({ option, values, selected, onSelect }: Props) {
  return (
    <View style={s.wrap}>
      <View style={s.head}>
        <Label>{option}</Label>
        <Micro style={s.chosen}>{selected ?? `Select ${option.toLowerCase()}`}</Micro>
      </View>
      <View style={s.row} accessibilityRole="radiogroup" accessibilityLabel={option}>
        {values.map((v) => (
          <OptionButton
            key={v.name}
            value={v}
            selected={selected === v.name}
            onPress={() => onSelect(v.name)}
          />
        ))}
      </View>
    </View>
  );
}

function OptionButton({ value, selected, onPress }: { value: OptionValue; selected: boolean; onPress: () => void }) {
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  const struck = value.soldOut || value.unavailableHere;
  const onLayout = (e: LayoutChangeEvent) => {
    const { width: w, height: h } = e.nativeEvent.layout;
    if (!box || box.w !== w || box.h !== h) setBox({ w, h });
  };
  const status = value.soldOut ? ', sold out' : value.unavailableHere ? ', not available in this combination' : '';

  return (
    <Pressable
      onLayout={onLayout}
      onPress={value.soldOut ? undefined : onPress}
      accessibilityRole="radio"
      accessibilityLabel={`${value.name}${status}`}
      accessibilityState={{ selected, disabled: value.soldOut }}
      style={({ pressed }) => [
        s.btn,
        selected && s.btnSelected,
        pressed && !selected && !value.soldOut && s.btnPressed,
      ]}
    >
      <Mono
        numberOfLines={1}
        style={[s.text, selected && s.textSelected, struck && !selected && s.textStruck]}
      >
        {value.name}
      </Mono>
      {struck && box ? <Strike w={box.w} h={box.h} /> : null}
    </Pressable>
  );
}

/**
 * Corner-to-corner strike, as on the website. A fixed 45° line only fits a
 * square; buttons here are as wide as their label, so the angle and length
 * come from the measured box.
 */
function Strike({ w, h }: { w: number; h: number }) {
  const len = Math.hypot(w, h);
  const angle = Math.atan2(h, w);
  return (
    <View
      pointerEvents="none"
      style={[
        s.strike,
        { width: len, left: (w - len) / 2, top: h / 2, transform: [{ rotate: `${-angle}rad` }] },
      ]}
    />
  );
}

const s = StyleSheet.create({
  wrap: { gap: 10 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  chosen: { color: colour.text },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  btn: {
    minWidth: TAP + 8,
    minHeight: TAP,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: colour.line,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  btnSelected: { backgroundColor: colour.purple, borderColor: colour.purple },
  btnPressed: { backgroundColor: colour.press },
  text: { fontFamily: font.mono, fontSize: 12, letterSpacing: 1.2, textTransform: 'uppercase' },
  textSelected: { color: colour.onPurple },
  textStruck: { color: colour.dim },
  strike: { position: 'absolute', height: 1, backgroundColor: colour.dim },
});
