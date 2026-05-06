#!/usr/bin/env python3
"""
DOOM skillm Action Vocabulary
==============================
Implements the /skillm procedural language model for the DOOM domain.

Composition: /skillm applied to DOOM game actions
  - Maps the 10 universal skillm verbs to DOOM-specific ticcmd_t semantics
  - Provides the semiring algebra (⊕ choice, ⊗ pipeline) for action composition
  - Defines the nn-to-skillm functor for DOOM neural network outputs

The Core Equation:
  ( ( ( * ) , ** ) , *** )
  Where:
    *   = nn.Module (single action: NAVIGATE, MUTATE, etc.)
    **  = function-creator (maps neural output to DOOM action)
    *** = skillm (the compiled action sequence AST)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import json


# =============================================================================
# skillm Verb Vocabulary (The 10 Universal Action Primitives)
# =============================================================================

class SkillmVerb(Enum):
    """
    The 10 primitive verbs from the skillm vocabulary,
    mapped to their DOOM-specific semantics.
    """
    DISCOVER = "DISCOVER"       # Scan environment for entities
    INSPECT = "INSPECT"         # Read detailed state of known entity
    CREATE = "CREATE"           # Interact/activate (doors, switches)
    MUTATE = "MUTATE"           # Attack/modify (fire weapon)
    DESTROY = "DESTROY"         # Kill enemy (sustained attack)
    NAVIGATE = "NAVIGATE"       # Move through the world
    COMPOSE = "COMPOSE"         # Complex multi-action (strafe+fire)
    OBSERVE = "OBSERVE"         # Capture metrics (check health/ammo)
    ORCHESTRATE = "ORCHESTRATE" # Multi-step planning (find key, open door)
    CLASSIFY = "CLASSIFY"       # Categorize threat level


# =============================================================================
# DOOM Action Space (ticcmd_t Field Semantics)
# =============================================================================

@dataclass
class DoomAction:
    """
    A single DOOM action corresponding to ticcmd_t fields.
    This is the atomic unit (*) in the tuple algebra.
    """
    forwardmove: int = 0    # -127 to 127 (backward/forward)
    sidemove: int = 0       # -127 to 127 (left/right strafe)
    angleturn: int = 0      # -32767 to 32767 (turn left/right)
    buttons: int = 0        # BT_ATTACK=1, BT_USE=2, BT_CHANGE=4
    duration: int = 1       # How many tics to hold this action
    verb: SkillmVerb = SkillmVerb.NAVIGATE
    
    def to_ticcmd_dict(self) -> Dict:
        return {
            "forwardmove": max(-127, min(127, self.forwardmove)),
            "sidemove": max(-127, min(127, self.sidemove)),
            "angleturn": max(-32767, min(32767, self.angleturn)),
            "buttons": self.buttons & 0xFF
        }
    
    def __repr__(self):
        parts = []
        if self.forwardmove: parts.append(f"fwd={self.forwardmove}")
        if self.sidemove: parts.append(f"side={self.sidemove}")
        if self.angleturn: parts.append(f"turn={self.angleturn}")
        if self.buttons: parts.append(f"btn=0x{self.buttons:02x}")
        return f"DoomAction({self.verb.value}: {', '.join(parts) or 'IDLE'})"


# =============================================================================
# Semiring Composition Operators (⊕ and ⊗)
# =============================================================================

@dataclass
class ActionSequence:
    """
    A sequence of DoomActions composed via the ⊗ (pipeline) operator.
    Represents: a1 ⊗ a2 ⊗ ... ⊗ an (execute in order)
    """
    actions: List[DoomAction] = field(default_factory=list)
    
    def pipeline(self, other: 'ActionSequence') -> 'ActionSequence':
        """⊗ operator: Sequential composition (execute self then other)"""
        return ActionSequence(actions=self.actions + other.actions)
    
    def __mul__(self, other):
        """Python operator overload for ⊗"""
        return self.pipeline(other)
    
    def total_duration(self) -> int:
        return sum(a.duration for a in self.actions)
    
    def current_action(self, tic: int) -> Optional[DoomAction]:
        """Get the action for a specific tic within the sequence."""
        elapsed = 0
        for action in self.actions:
            if elapsed + action.duration > tic:
                return action
            elapsed += action.duration
        return self.actions[-1] if self.actions else None


@dataclass
class ActionChoice:
    """
    A choice between ActionSequences composed via the ⊕ (choice) operator.
    Represents: a1 ⊕ a2 ⊕ ... ⊕ an (choose one based on condition)
    """
    alternatives: List[Tuple[str, ActionSequence]] = field(default_factory=list)
    
    def choice(self, other_name: str, other: ActionSequence) -> 'ActionChoice':
        """⊕ operator: Add an alternative"""
        return ActionChoice(
            alternatives=self.alternatives + [(other_name, other)]
        )
    
    def __add__(self, other):
        """Python operator overload for ⊕"""
        if isinstance(other, tuple):
            return self.choice(other[0], other[1])
        return self
    
    def select(self, condition: str) -> Optional[ActionSequence]:
        """Select an alternative based on a condition string."""
        for name, seq in self.alternatives:
            if name == condition:
                return seq
        return self.alternatives[0][1] if self.alternatives else None


# =============================================================================
# DOOM Action Library (Pre-composed Sequences)
# =============================================================================

# --- Atomic Actions (nn.Linear equivalents) ---

MOVE_FORWARD = DoomAction(forwardmove=50, verb=SkillmVerb.NAVIGATE, duration=7)
MOVE_BACKWARD = DoomAction(forwardmove=-50, verb=SkillmVerb.NAVIGATE, duration=7)
TURN_LEFT = DoomAction(angleturn=1200, verb=SkillmVerb.NAVIGATE, duration=3)
TURN_RIGHT = DoomAction(angleturn=-1200, verb=SkillmVerb.NAVIGATE, duration=3)
STRAFE_LEFT = DoomAction(sidemove=-40, verb=SkillmVerb.NAVIGATE, duration=5)
STRAFE_RIGHT = DoomAction(sidemove=40, verb=SkillmVerb.NAVIGATE, duration=5)
FIRE = DoomAction(buttons=1, verb=SkillmVerb.MUTATE, duration=7)
USE = DoomAction(buttons=2, verb=SkillmVerb.CREATE, duration=3)
IDLE = DoomAction(verb=SkillmVerb.OBSERVE, duration=7)

# --- Composed Sequences (nn.Sequential equivalents) ---

ATTACK_ADVANCE = ActionSequence([
    DoomAction(forwardmove=30, buttons=1, verb=SkillmVerb.COMPOSE, duration=7),
])

CIRCLE_STRAFE_LEFT = ActionSequence([
    DoomAction(forwardmove=20, sidemove=-30, angleturn=400, buttons=1, 
               verb=SkillmVerb.COMPOSE, duration=7),
])

CIRCLE_STRAFE_RIGHT = ActionSequence([
    DoomAction(forwardmove=20, sidemove=30, angleturn=-400, buttons=1, 
               verb=SkillmVerb.COMPOSE, duration=7),
])

RETREAT_FIRE = ActionSequence([
    DoomAction(forwardmove=-40, buttons=1, verb=SkillmVerb.COMPOSE, duration=7),
])

DODGE_LEFT = ActionSequence([
    DoomAction(sidemove=-50, verb=SkillmVerb.NAVIGATE, duration=5),
    DoomAction(sidemove=0, verb=SkillmVerb.OBSERVE, duration=2),
])

DODGE_RIGHT = ActionSequence([
    DoomAction(sidemove=50, verb=SkillmVerb.NAVIGATE, duration=5),
    DoomAction(sidemove=0, verb=SkillmVerb.OBSERVE, duration=2),
])

EXPLORE_FORWARD = ActionSequence([
    DoomAction(forwardmove=50, verb=SkillmVerb.NAVIGATE, duration=14),
    DoomAction(angleturn=600, verb=SkillmVerb.DISCOVER, duration=7),
    DoomAction(angleturn=-600, verb=SkillmVerb.DISCOVER, duration=7),
])

OPEN_DOOR = ActionSequence([
    DoomAction(forwardmove=30, verb=SkillmVerb.NAVIGATE, duration=5),
    DoomAction(buttons=2, verb=SkillmVerb.CREATE, duration=3),
    DoomAction(forwardmove=50, verb=SkillmVerb.NAVIGATE, duration=10),
])


# =============================================================================
# Tactical Decision Engine (The function-creator Functor)
# =============================================================================

class DoomTactician:
    """
    The function-creator (**) that maps game state observations to
    skillm action sequences. This is the nn -> skillm functor.
    
    Implements a reactive policy using the skillm semiring:
      combat_policy = (face_enemy ⊗ fire) ⊕ (dodge ⊗ retreat)
      explore_policy = (move_forward ⊗ scan) ⊕ (open_door)
    """
    
    def __init__(self):
        self.last_action = None
        self.action_tic = 0
        self.current_sequence = None
        self.sequence_tic = 0
    
    def decide(self, state: Dict) -> Dict:
        """
        Main decision function. Takes game state, returns ticcmd_t dict.
        Implements the full DSPU pipeline: observe -> decide -> act.
        """
        health = state.get("health", 100)
        ammo = state.get("ammo", 50)
        enemies = state.get("enemies", [])
        
        # If we have an active sequence, continue it
        if self.current_sequence and self.sequence_tic < self.current_sequence.total_duration():
            action = self.current_sequence.current_action(self.sequence_tic)
            self.sequence_tic += 7  # Advance by decision interval
            if action:
                return action.to_ticcmd_dict()
        
        # Select new action sequence based on state
        if enemies:
            sequence = self._combat_policy(state, enemies, health, ammo)
        else:
            sequence = self._explore_policy(state)
        
        self.current_sequence = sequence
        self.sequence_tic = 0
        
        action = sequence.current_action(0)
        self.sequence_tic += 7
        return action.to_ticcmd_dict() if action else IDLE.to_ticcmd_dict()
    
    def _combat_policy(self, state, enemies, health, ammo):
        """
        Combat decision tree using skillm semiring composition.
        
        Policy = (low_health ⊕ has_ammo ⊕ no_ammo)
        Where:
          low_health = RETREAT_FIRE ⊗ DODGE
          has_ammo   = FACE_ENEMY ⊗ ATTACK
          no_ammo    = RETREAT ⊗ EXPLORE (find ammo)
        """
        closest = min(enemies, key=lambda e: e.get("dist", 9999))
        dist = closest.get("dist", 9999)
        angle = closest.get("angle", 0)
        
        # Choice operator ⊕: select based on condition
        if health < 30 and dist < 200:
            # Low health, close enemy: retreat and dodge
            return RETREAT_FIRE
        elif ammo <= 0:
            # No ammo: retreat
            return ActionSequence([MOVE_BACKWARD])
        elif abs(angle) > 500:
            # Enemy not in front: turn to face
            if angle > 0:
                return ActionSequence([TURN_LEFT])
            else:
                return ActionSequence([TURN_RIGHT])
        elif dist > 400:
            # Far enemy: advance while firing
            return ATTACK_ADVANCE
        elif dist < 150:
            # Close enemy: circle strafe
            if self.sequence_tic % 14 < 7:
                return CIRCLE_STRAFE_LEFT
            else:
                return CIRCLE_STRAFE_RIGHT
        else:
            # Medium range: fire and strafe
            return ActionSequence([
                DoomAction(forwardmove=10, sidemove=25, buttons=1,
                          verb=SkillmVerb.COMPOSE, duration=7)
            ])
    
    def _explore_policy(self, state):
        """
        Exploration policy using skillm pipeline composition.
        
        Policy = MOVE_FORWARD ⊗ SCAN ⊗ (OPEN_DOOR ⊕ TURN)
        """
        return EXPLORE_FORWARD


# =============================================================================
# Integration with ai_server.py
# =============================================================================

def create_tactician():
    """Factory function for use by ai_server.py"""
    return DoomTactician()


# =============================================================================
# CLI Demo
# =============================================================================

if __name__ == "__main__":
    print("=== DOOM skillm Action Vocabulary Demo ===\n")
    
    tactician = DoomTactician()
    
    # Simulate combat scenario
    combat_state = {
        "health": 80,
        "ammo": 30,
        "armor": 50,
        "enemies": [
            {"type": 1, "angle": 200, "dist": 250, "health": 30},
            {"type": 2, "angle": -800, "dist": 500, "health": 60},
        ]
    }
    
    print("Combat State:", json.dumps(combat_state, indent=2))
    print("\nDecision sequence (7 tics each):")
    for i in range(5):
        cmd = tactician.decide(combat_state)
        print(f"  Tic {i*7:3d}: {cmd}")
    
    print("\n--- Exploration ---")
    tactician2 = DoomTactician()
    explore_state = {"health": 100, "ammo": 50, "armor": 0, "enemies": []}
    
    print("Explore State:", json.dumps(explore_state, indent=2))
    print("\nDecision sequence:")
    for i in range(5):
        cmd = tactician2.decide(explore_state)
        print(f"  Tic {i*7:3d}: {cmd}")
    
    print("\n--- Semiring Algebra Demo ---")
    print(f"ATTACK_ADVANCE ⊗ DODGE_LEFT (pipeline):")
    combined = ATTACK_ADVANCE * DODGE_LEFT
    for i, a in enumerate(combined.actions):
        print(f"  Step {i}: {a}")
    
    print(f"\nTotal duration: {combined.total_duration()} tics")
