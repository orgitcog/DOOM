// ai_player.c - DOOM AI Player Integration (DSPU Game Loop Hook)
//-----------------------------------------------------------------------------
//
// DESCRIPTION:
//   Implements the AI player controller that hooks into the DOOM game loop.
//   Extracts game state, communicates with the GGUF inference server via
//   Unix socket, and injects ticcmd_t commands into the player's command buffer.
//
//   DSPU Architecture:
//     Front End:  AI_ExtractGameState (observation)
//     Fabric:     Unix socket -> ai_server.py -> llama.cpp (inference)
//     Back End:   AI_BuildTiccmd (action injection)
//
//   Composition: /dspu-architecture-design
//     /nn [ /ggml-spec | /llama-cpp-spec ] -> /llamacpu -> /skillm
//
//-----------------------------------------------------------------------------

// DOOM headers first (before POSIX headers to avoid name conflicts
// with p_spec.h's 'open'/'close' enum values)
#include "doomdef.h"
#include "doomstat.h"
#include "d_player.h"
#include "p_mobj.h"
#include "p_local.h"
#include "r_main.h"
#include "r_state.h"
#include "m_fixed.h"
#include "tables.h"
#include "info.h"

// POSIX/system headers
// NOTE: We cannot include <unistd.h> because p_spec.h defines
// 'close' and 'open' as enum values, conflicting with POSIX.
// Instead we declare the few POSIX functions we need directly.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/time.h>
#include <arpa/inet.h>

// Manual declarations to avoid unistd.h / p_spec.h conflict
int ai_close(int fd);
int ai_close(int fd) { return shutdown(fd, 2); }
// We use shutdown() as a workaround since close() is an enum in p_spec.h

#include "ai_player.h"

// --- Global AI State ---
static ai_state_t ai_state = {0};

// --- Forward declarations ---
static int  ai_send_state(ai_game_state_t* state);
static int  ai_recv_cmd(ticcmd_t* cmd);
static void ai_fallback_cmd(ticcmd_t* cmd, int playernum);
static int  ai_is_enemy(mobj_t* thing);
static int  ai_calc_distance(fixed_t x1, fixed_t y1, fixed_t x2, fixed_t y2);
static int  ai_calc_relative_angle(mobj_t* player_mo, mobj_t* target);

// ============================================================================
// Public API
// ============================================================================

void AI_Init(int player_num)
{
    memset(&ai_state, 0, sizeof(ai_state));
    ai_state.player_num = player_num;
    ai_state.enabled = 1;
    ai_state.connected = 0;
    ai_state.socket_fd = -1;
    ai_state.tic_counter = 0;
    memset(&ai_state.current_cmd, 0, sizeof(ticcmd_t));
    
    printf("[DOOM-AI] AI Player initialized for player %d\n", player_num);
    printf("[DOOM-AI] Decision interval: %d tics (~%dms)\n", 
           AI_DECISION_TICS, (AI_DECISION_TICS * 1000) / TICRATE);
    
    // Try to connect immediately
    AI_Connect();
}

void AI_Shutdown(void)
{
    if (ai_state.socket_fd >= 0) {
        ai_close(ai_state.socket_fd);
        ai_state.socket_fd = -1;
    }
    ai_state.connected = 0;
    ai_state.enabled = 0;
    printf("[DOOM-AI] AI Player shutdown\n");
}

int AI_Connect(void)
{
    struct sockaddr_un addr;
    struct timeval tv;
    
    if (ai_state.socket_fd >= 0) {
        ai_close(ai_state.socket_fd);
    }
    
    ai_state.socket_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (ai_state.socket_fd < 0) {
        printf("[DOOM-AI] Failed to create socket: %s\n", strerror(errno));
        ai_state.connected = 0;
        return 0;
    }
    
    // Set socket timeout
    tv.tv_sec = 0;
    tv.tv_usec = AI_TIMEOUT_MS * 1000;
    setsockopt(ai_state.socket_fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(ai_state.socket_fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, AI_SOCKET_PATH, sizeof(addr.sun_path) - 1);
    
    if (connect(ai_state.socket_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        // Not an error during startup - server might not be running yet
        ai_close(ai_state.socket_fd);
        ai_state.socket_fd = -1;
        ai_state.connected = 0;
        return 0;
    }
    
    ai_state.connected = 1;
    printf("[DOOM-AI] Connected to inference server at %s\n", AI_SOCKET_PATH);
    return 1;
}

void AI_BuildTiccmd(ticcmd_t* cmd, int playernum)
{
    ai_game_state_t game_state;
    
    if (!ai_state.enabled || playernum != ai_state.player_num)
        return;
    
    // Only make a new decision every AI_DECISION_TICS
    ai_state.tic_counter++;
    
    if (ai_state.tic_counter >= AI_DECISION_TICS) {
        ai_state.tic_counter = 0;
        
        // Try to reconnect if disconnected
        if (!ai_state.connected) {
            AI_Connect();
        }
        
        if (ai_state.connected) {
            // Extract game state (DSPU Front End: Observation)
            AI_ExtractGameState(&game_state, playernum);
            
            // Send state and receive command (DSPU Fabric: Inference)
            if (ai_send_state(&game_state)) {
                ticcmd_t new_cmd;
                memset(&new_cmd, 0, sizeof(ticcmd_t));
                if (ai_recv_cmd(&new_cmd)) {
                    memcpy(&ai_state.current_cmd, &new_cmd, sizeof(ticcmd_t));
                } else {
                    // Communication failed, use fallback
                    ai_fallback_cmd(&ai_state.current_cmd, playernum);
                    ai_state.connected = 0;
                }
            } else {
                ai_fallback_cmd(&ai_state.current_cmd, playernum);
                ai_state.connected = 0;
            }
        } else {
            // No server connection, use built-in heuristic
            ai_fallback_cmd(&ai_state.current_cmd, playernum);
        }
    }
    
    // Apply the current command (DSPU Back End: Action Injection)
    cmd->forwardmove = ai_state.current_cmd.forwardmove;
    cmd->sidemove = ai_state.current_cmd.sidemove;
    cmd->angleturn = ai_state.current_cmd.angleturn;
    cmd->buttons = ai_state.current_cmd.buttons;
}

void AI_ExtractGameState(ai_game_state_t* state, int playernum)
{
    player_t* player;
    mobj_t* player_mo;
    thinker_t* th;
    mobj_t* mo;
    int enemy_count = 0;
    
    memset(state, 0, sizeof(ai_game_state_t));
    
    if (!playeringame[playernum])
        return;
    
    player = &players[playernum];
    player_mo = player->mo;
    
    if (!player_mo)
        return;
    
    // Basic player stats
    state->health = player->health;
    state->armor = player->armorpoints;
    state->weapon = player->readyweapon;
    state->x = player_mo->x >> FRACBITS;
    state->y = player_mo->y >> FRACBITS;
    state->angle = player_mo->angle >> 16;  // Convert to 16-bit angle
    state->on_ground = (player_mo->z <= player_mo->floorz) ? 1 : 0;
    
    // Current weapon ammo
    if (player->readyweapon < NUMWEAPONS) {
        ammotype_t ammo_type;
        // Map weapon to ammo type
        switch (player->readyweapon) {
            case wp_pistol:
            case wp_chaingun:
                ammo_type = am_clip;
                break;
            case wp_shotgun:
            case wp_supershotgun:
                ammo_type = am_shell;
                break;
            case wp_plasma:
            case wp_bfg:
                ammo_type = am_cell;
                break;
            case wp_missile:
                ammo_type = am_misl;
                break;
            default:
                ammo_type = am_noammo;
                break;
        }
        if (ammo_type != am_noammo)
            state->ammo = player->ammo[ammo_type];
        else
            state->ammo = 999;  // Fist/chainsaw = unlimited
    }
    
    // Scan for visible enemies (iterate thinker list)
    for (th = thinkercap.next; th != &thinkercap; th = th->next) {
        if (th->function.acp1 != (actionf_p1)P_MobjThinker)
            continue;
        
        mo = (mobj_t*)th;
        
        // Check if it's an enemy
        if (!ai_is_enemy(mo))
            continue;
        
        // Check if alive
        if (mo->health <= 0)
            continue;
        
        // Check line of sight (expensive but necessary for realism)
        if (!P_CheckSight(player_mo, mo))
            continue;
        
        // Record this enemy
        if (enemy_count < AI_MAX_ENEMIES) {
            state->enemies[enemy_count].type = mo->type;
            state->enemies[enemy_count].health = mo->health;
            state->enemies[enemy_count].distance = 
                ai_calc_distance(player_mo->x, player_mo->y, mo->x, mo->y);
            state->enemies[enemy_count].angle = 
                ai_calc_relative_angle(player_mo, mo);
            enemy_count++;
        }
    }
    state->num_enemies = enemy_count;
}

int AI_IsControlling(int playernum)
{
    return (ai_state.enabled && playernum == ai_state.player_num);
}

void AI_SetEnabled(int enabled)
{
    ai_state.enabled = enabled;
    if (!enabled) {
        memset(&ai_state.current_cmd, 0, sizeof(ticcmd_t));
    }
}

// ============================================================================
// Private Implementation
// ============================================================================

static int ai_send_state(ai_game_state_t* state)
{
    char buf[4096];
    int len;
    unsigned int net_len;
    int i;
    
    // Serialize state to JSON
    len = snprintf(buf, sizeof(buf),
        "{\"health\":%d,\"armor\":%d,\"ammo\":%d,\"weapon\":%d,"
        "\"x\":%d,\"y\":%d,\"angle\":%d,\"on_ground\":%d,\"enemies\":[",
        state->health, state->armor, state->ammo, state->weapon,
        state->x, state->y, state->angle, state->on_ground);
    
    for (i = 0; i < state->num_enemies && i < AI_MAX_ENEMIES; i++) {
        if (i > 0) len += snprintf(buf + len, sizeof(buf) - len, ",");
        len += snprintf(buf + len, sizeof(buf) - len,
            "{\"type\":%d,\"angle\":%d,\"dist\":%d,\"health\":%d}",
            state->enemies[i].type,
            state->enemies[i].angle,
            state->enemies[i].distance,
            state->enemies[i].health);
    }
    len += snprintf(buf + len, sizeof(buf) - len, "]}");
    
    // Send length-prefixed message
    net_len = htonl((unsigned int)len);
    if (send(ai_state.socket_fd, &net_len, 4, 0) != 4)
        return 0;
    if (send(ai_state.socket_fd, buf, len, 0) != len)
        return 0;
    
    return 1;
}

static int ai_recv_cmd(ticcmd_t* cmd)
{
    unsigned int net_len;
    int msg_len;
    char buf[1024];
    int fwd = 0, side = 0, turn = 0, buttons = 0;
    
    // Receive length prefix
    if (recv(ai_state.socket_fd, &net_len, 4, 0) != 4)
        return 0;
    
    msg_len = ntohl(net_len);
    if (msg_len <= 0 || msg_len >= (int)sizeof(buf))
        return 0;
    
    // Receive JSON payload
    if (recv(ai_state.socket_fd, buf, msg_len, 0) != msg_len)
        return 0;
    buf[msg_len] = '\0';
    
    // Simple JSON parsing (avoid external dependency)
    // Format: {"forwardmove":N,"sidemove":N,"angleturn":N,"buttons":N}
    sscanf(buf, "{\"forwardmove\":%d,\"sidemove\":%d,\"angleturn\":%d,\"buttons\":%d}",
           &fwd, &side, &turn, &buttons);
    
    // Clamp values to valid ranges
    if (fwd > 127) fwd = 127;
    if (fwd < -127) fwd = -127;
    if (side > 127) side = 127;
    if (side < -127) side = -127;
    if (turn > 32767) turn = 32767;
    if (turn < -32767) turn = -32767;
    
    cmd->forwardmove = (char)fwd;
    cmd->sidemove = (char)side;
    cmd->angleturn = (short)turn;
    cmd->buttons = (byte)(buttons & 0xFF);
    
    return 1;
}

static void ai_fallback_cmd(ticcmd_t* cmd, int playernum)
{
    // Built-in reactive AI when inference server is unavailable
    // This is a simplified version of the heuristic in ai_server.py
    player_t* player;
    mobj_t* player_mo;
    ai_game_state_t state;
    
    memset(cmd, 0, sizeof(ticcmd_t));
    
    if (!playeringame[playernum])
        return;
    
    player = &players[playernum];
    player_mo = player->mo;
    
    if (!player_mo || player->playerstate == PST_DEAD)
        return;
    
    // Extract state for decision making
    AI_ExtractGameState(&state, playernum);
    
    if (state.num_enemies > 0) {
        // Combat mode: face closest enemy and fire
        int closest_idx = 0;
        int closest_dist = state.enemies[0].distance;
        int i;
        
        for (i = 1; i < state.num_enemies; i++) {
            if (state.enemies[i].distance < closest_dist) {
                closest_dist = state.enemies[i].distance;
                closest_idx = i;
            }
        }
        
        int rel_angle = state.enemies[closest_idx].angle;
        
        // Turn toward enemy
        if (rel_angle > 200)
            cmd->angleturn = 800;
        else if (rel_angle < -200)
            cmd->angleturn = -800;
        else if (rel_angle > 50)
            cmd->angleturn = 300;
        else if (rel_angle < -50)
            cmd->angleturn = -300;
        
        // Fire if roughly facing
        if (abs(rel_angle) < 400 && state.ammo > 0)
            cmd->buttons |= 1;  // BT_ATTACK
        
        // Movement based on distance and health
        if (closest_dist > 300)
            cmd->forwardmove = 50;
        else if (closest_dist < 100 && state.health < 40) {
            cmd->forwardmove = -40;
            cmd->sidemove = 25;
        } else {
            cmd->forwardmove = 20;
            // Strafe to dodge
            cmd->sidemove = (gametic % 14 < 7) ? 25 : -25;
        }
    } else {
        // Exploration mode: move forward, occasionally turn
        cmd->forwardmove = 50;
        if (gametic % 35 < 5)
            cmd->angleturn = 400;
        else if (gametic % 35 > 30)
            cmd->angleturn = -400;
    }
}

static int ai_is_enemy(mobj_t* thing)
{
    // Check if a mobj is a shootable enemy
    if (!(thing->flags & MF_SHOOTABLE))
        return 0;
    if (!(thing->flags & MF_COUNTKILL))
        return 0;
    return 1;
}

static int ai_calc_distance(fixed_t x1, fixed_t y1, fixed_t x2, fixed_t y2)
{
    // Approximate distance in map units
    fixed_t dx = abs(x2 - x1) >> FRACBITS;
    fixed_t dy = abs(y2 - y1) >> FRACBITS;
    
    // Fast approximation: max(dx,dy) + min(dx,dy)/2
    if (dx > dy)
        return dx + (dy >> 1);
    else
        return dy + (dx >> 1);
}

static int ai_calc_relative_angle(mobj_t* player_mo, mobj_t* target)
{
    // Calculate the angle from player to target, relative to player's facing
    angle_t abs_angle;
    angle_t rel_angle;
    
    abs_angle = R_PointToAngle2(player_mo->x, player_mo->y, 
                                 target->x, target->y);
    rel_angle = abs_angle - player_mo->angle;
    
    // Convert to signed 16-bit value for the AI
    // Positive = target is to the left, Negative = target is to the right
    return (int)((short)(rel_angle >> 16));
}
