"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import type { UIArtifact } from "@/components/artifact";

export const initialArtifactData: UIArtifact = {
  documentId: "init",
  content: "",
  kind: "text",
  title: "",
  status: "idle",
  isVisible: false,
  boundingBox: {
    top: 0,
    left: 0,
    width: 0,
    height: 0,
  },
};

// 아티팩트 배열 상태 타입
interface ArtifactState {
  artifacts: UIArtifact[];
  activeArtifactIndex: number;
}

const initialArtifactState: ArtifactState = {
  artifacts: [],
  activeArtifactIndex: -1,
};

type Selector<T> = (state: UIArtifact) => T;

/**
 * 단일 아티팩트 selector (하위 호환성)
 * @deprecated 배열 기반 useArtifacts() 사용 권장
 */
export function useArtifactSelector<Selected>(selector: Selector<Selected>) {
  const { data: artifactState } = useSWR<ArtifactState>("artifact-state", null, {
    fallbackData: initialArtifactState,
  });

  const currentArtifact = useMemo(() => {
    if (!artifactState || artifactState.activeArtifactIndex === -1) {
      return initialArtifactData;
    }
    return artifactState.artifacts[artifactState.activeArtifactIndex] || initialArtifactData;
  }, [artifactState]);

  const selectedValue = useMemo(() => {
    return selector(currentArtifact);
  }, [currentArtifact, selector]);

  return selectedValue;
}

/**
 * 단일 아티팩트 훅 (하위 호환성)
 * @deprecated 배열 기반 useArtifacts() 사용 권장
 */
export function useArtifact() {
  const { data: artifactState, mutate: setArtifactState } = useSWR<ArtifactState>(
    "artifact-state",
    null,
    {
      fallbackData: initialArtifactState,
    }
  );

  const artifact = useMemo(() => {
    if (!artifactState || artifactState.activeArtifactIndex === -1) {
      return initialArtifactData;
    }
    return artifactState.artifacts[artifactState.activeArtifactIndex] || initialArtifactData;
  }, [artifactState]);

  const setArtifact = useCallback(
    (updaterFn: UIArtifact | ((currentArtifact: UIArtifact) => UIArtifact)) => {
      setArtifactState((currentState) => {
        const state = currentState || initialArtifactState;
        const artifactToUpdate = state.activeArtifactIndex >= 0
          ? state.artifacts[state.activeArtifactIndex]
          : initialArtifactData;

        const updatedArtifact = typeof updaterFn === "function"
          ? updaterFn(artifactToUpdate)
          : updaterFn;

        if (state.activeArtifactIndex === -1) {
          // 첫 번째 아티팩트 추가
          return {
            artifacts: [updatedArtifact],
            activeArtifactIndex: 0,
          };
        }

        // 기존 아티팩트 업데이트
        const newArtifacts = [...state.artifacts];
        newArtifacts[state.activeArtifactIndex] = updatedArtifact;
        return {
          ...state,
          artifacts: newArtifacts,
        };
      });
    },
    [setArtifactState]
  );

  const { data: localArtifactMetadata, mutate: setLocalArtifactMetadata } =
    useSWR<any>(
      () =>
        artifact.documentId ? `artifact-metadata-${artifact.documentId}` : null,
      null,
      {
        fallbackData: null,
      }
    );

  return useMemo(
    () => ({
      artifact,
      setArtifact,
      metadata: localArtifactMetadata,
      setMetadata: setLocalArtifactMetadata,
    }),
    [artifact, setArtifact, localArtifactMetadata, setLocalArtifactMetadata]
  );
}

/**
 * 여러 아티팩트를 관리하는 훅 (새로운 배열 기반 API)
 */
export function useArtifacts() {
  const { data: artifactState, mutate: setArtifactState } = useSWR<ArtifactState>(
    "artifact-state",
    null,
    {
      fallbackData: initialArtifactState,
    }
  );

  const state = artifactState || initialArtifactState;

  // 새 아티팩트 추가
  const addArtifact = useCallback(
    (artifact: UIArtifact) => {
      setArtifactState((currentState) => {
        const state = currentState || initialArtifactState;
        return {
          artifacts: [...state.artifacts, artifact],
          activeArtifactIndex: state.artifacts.length, // 새 아티팩트를 활성화
        };
      });
    },
    [setArtifactState]
  );

  // 아티팩트 선택
  const selectArtifact = useCallback(
    (index: number) => {
      setArtifactState((currentState) => {
        const state = currentState || initialArtifactState;
        if (index < 0 || index >= state.artifacts.length) {
          return state;
        }
        return {
          ...state,
          activeArtifactIndex: index,
        };
      });
    },
    [setArtifactState]
  );

  // 특정 아티팩트 업데이트
  const updateArtifact = useCallback(
    (index: number, updates: Partial<UIArtifact>) => {
      setArtifactState((currentState) => {
        const state = currentState || initialArtifactState;
        if (index < 0 || index >= state.artifacts.length) {
          return state;
        }
        const newArtifacts = [...state.artifacts];
        newArtifacts[index] = { ...newArtifacts[index], ...updates };
        return {
          ...state,
          artifacts: newArtifacts,
        };
      });
    },
    [setArtifactState]
  );

  // 아티팩트 제거
  const removeArtifact = useCallback(
    (index: number) => {
      setArtifactState((currentState) => {
        const state = currentState || initialArtifactState;
        if (index < 0 || index >= state.artifacts.length) {
          return state;
        }
        const newArtifacts = state.artifacts.filter((_, i) => i !== index);
        const newActiveIndex = state.activeArtifactIndex === index
          ? Math.max(0, state.activeArtifactIndex - 1)
          : state.activeArtifactIndex > index
          ? state.activeArtifactIndex - 1
          : state.activeArtifactIndex;

        return {
          artifacts: newArtifacts,
          activeArtifactIndex: newArtifacts.length > 0 ? newActiveIndex : -1,
        };
      });
    },
    [setArtifactState]
  );

  // 모든 아티팩트 클리어
  const clearArtifacts = useCallback(() => {
    setArtifactState(initialArtifactState);
  }, [setArtifactState]);

  const currentArtifact = useMemo(() => {
    if (state.activeArtifactIndex === -1) {
      return null;
    }
    return state.artifacts[state.activeArtifactIndex] || null;
  }, [state]);

  return useMemo(
    () => ({
      artifacts: state.artifacts,
      activeArtifactIndex: state.activeArtifactIndex,
      currentArtifact,
      addArtifact,
      selectArtifact,
      updateArtifact,
      removeArtifact,
      clearArtifacts,
    }),
    [state, currentArtifact, addArtifact, selectArtifact, updateArtifact, removeArtifact, clearArtifacts]
  );
}
