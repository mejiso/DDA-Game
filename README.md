# DDA-Game
Dynamic Difficulty Adjustment Game Space Dodge Game
Simple Prototype made with Python & Pygame

# Game Parameters

Game Parameters that Adjust Difficulty

- Near Misses
- Collisions/Hits
- Movement

# Difficulty Parameters

Difficulty Parameters that Adjust based on Game

- Meteor Fall speed
- Meteor Spawn Interval

# Logs

Logs Data throughout Gameplay Sessions

----- sessions.csv ------

ts_start,ts_end,session_id,subject_id,protocol_version,notes,config_json,duration_sec,final_difficulty,lives_remaining,shields_collected,near_misses,meteors_spawned,meteors_avoided

------ events.csv ------

ts,session_id,type,detail_json

------ blocks.csv ------

ts_start,ts_end,session_id,block_idx,duration_sec,difficulty_avg,speed_scale_avg,meteors_spawned,meteors_avoided,hits,near_misses,movement_px,success_rate

