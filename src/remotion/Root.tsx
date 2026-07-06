import React from "react";
import { Composition } from "remotion";
import { UGCAd } from "./UGCAd";
import type { UGCAdProps } from "../types";

const defaultProps: UGCAdProps = {
  fps: 30,
  width: 1080,
  height: 1920,
  hook: "Okay this is genius",
  segments: [
    { clip: "", start: 0, duration: 2, punchIn: 0.06 },
    { clip: "", start: 2, duration: 2, punchIn: 0.1 },
  ],
  voiceover: {
    src: "",
    duration: 4,
    words: [
      { word: "Okay", start: 0, end: 0.4 },
      { word: "this", start: 0.4, end: 0.8 },
      { word: "is", start: 0.8, end: 1.1 },
      { word: "genius", start: 1.1, end: 1.8 },
    ],
  },
  music: null,
  captionStyle: { fontFamily: "Poppins", activeColor: "#FFE24B", baseColor: "#FFFFFF" },
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="UGCAd"
      component={UGCAd}
      durationInFrames={120}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={defaultProps}
      calculateMetadata={({ props }) => {
        const fps = props.fps ?? 30;
        const seconds = props.voiceover?.duration ?? 4;
        return {
          durationInFrames: Math.max(1, Math.round(seconds * fps)),
          fps,
          width: props.width ?? 1080,
          height: props.height ?? 1920,
        };
      }}
    />
  );
};
