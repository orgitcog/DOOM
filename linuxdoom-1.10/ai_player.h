// ai_player.h - DOOM AI Player Integration (DSPU Game Loop Hook)
//-----------------------------------------------------------------------------
//
// DESCRIPTION:
//   AI Player controller that integrates GGUF/llama.cpp inference into the
//   DOOM game loop. Communicates with an external Python inference server
//   via Unix socket to receive ticcmd_t commands.
//
//   Architecture: /dspu-architecture-design
//   Composition:  /nn [ /ggml-spec | /llama-cpp-spec ] -> /llamacpu -> /skillm
//
//-----------------------------------------------------------------------------

#ifndef __AI_PLAYER__
#define __AI_PLAYER__

#include "d_ticcmd.h"
#include "d_player.h"
#include "doomdef.h"

#ifdef __GNUG__
#pragma interface
#endif

// AI Player configuration
#define AI_SOCKET_PATH      "/tmp/doom_ai.sock"
#define AI_DECISION_TICS    7       // Run inference every N tics (~200ms at 35Hz)
#define AI_TIMEOUT_MS       100     // Socket timeout in milliseconds
#define AI_MAX_ENEMIES      8       // Max enemies to report in state

// AI Player state
typedef struct
{
    int         enabled;            // Is AI player active?
    int         connected;          // Is socket connected to inference server?
    int         socket_fd;          // Unix socket file descriptor
    int         tic_counter;        // Tics since last decision
    ticcmd_t    current_cmd;        // Current command being executed
    int         player_num;         // Which player slot the AI controls
} ai_state_t;

// Enemy observation for state extraction
typedef struct
{
    int         type;               // mobjtype_t
    int         angle;              // Relative angle from player (ANG units)
    int         distance;           // Distance in map units
    int         health;             // Enemy health
} ai_enemy_obs_t;

// Game state observation sent to inference server
typedef struct
{
    int         health;
    int         armor;
    int         ammo;               // Current weapon ammo
    int         weapon;             // Current weapon type
    int         x;                  // Player position
    int         y;
    int         angle;              // Player facing angle
    int         on_ground;          // Is player on the floor?
    int         num_enemies;
    ai_enemy_obs_t enemies[AI_MAX_ENEMIES];
} ai_game_state_t;

// --- Public API ---

// Initialize the AI player system
void AI_Init(int player_num);

// Shutdown the AI player system
void AI_Shutdown(void);

// Connect to the inference server
int AI_Connect(void);

// Build a ticcmd for the AI player (called from G_BuildTiccmd or NetUpdate)
void AI_BuildTiccmd(ticcmd_t* cmd, int playernum);

// Extract current game state for the AI
void AI_ExtractGameState(ai_game_state_t* state, int playernum);

// Check if AI is controlling a specific player
int AI_IsControlling(int playernum);

// Enable/disable AI player
void AI_SetEnabled(int enabled);

#endif // __AI_PLAYER__
