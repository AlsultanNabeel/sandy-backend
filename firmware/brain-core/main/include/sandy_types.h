#pragma once
#include <stdint.h>
#include <stdbool.h>

typedef enum {
    MOOD_IDLE = 0,
    MOOD_HAPPY,
    MOOD_CURIOUS,
    MOOD_SAD,
    MOOD_ALERT,
    MOOD_SURPRISED,
    MOOD_BIG_HAPPY,
    MOOD_FOCUSED,
    MOOD_BORED,
    MOOD_EXCITED,
    MOOD_LOVE,
    MOOD_ANGRY,
    MOOD_CONFUSED,
    MOOD_THINKING,
    MOOD_SLEEPY,
    MOOD_SHY,
    MOOD_PROUD,
    MOOD_WORRIED,
    MOOD_PLAYFUL,
    MOOD_CALM,
    MOOD_GRUMPY,
    MOOD_HOPEFUL,
    MOOD_GRATEFUL,
    MOOD_DISAPPOINTED,
    MOOD_SILLY,
    MOOD_COUNT
} sandy_mood_t;

typedef enum {
    MELODY_NONE = 0,
    MELODY_BOOT,
    MELODY_HAPPY,
    MELODY_CURIOUS,
    MELODY_SAD,
    MELODY_ALERT,
    MELODY_ERROR,
    MELODY_FOCUS_START,
    MELODY_FOCUS_BREAK,
    MELODY_FOCUS_END,
    // ── نغمات تانية للمزاج والتفاعل ──
    // الجرس بيزو سلبي: بيعزف أي تردد، فالنغمة قائمة نوتات مش صوت مسجّل.
    // إضافة وحدة = سطر هون + مصفوفة بـ sandy_buzzer.c + اسم بجدول MQTT.
    MELODY_HELLO,       // ترحيب قصير لما تناديها
    MELODY_BYE,         // وداع هابط
    MELODY_YES,         // تأكيد صاعد نوتتين
    MELODY_NO,          // رفض هابط نوتتين
    MELODY_THINKING,    // نقرات خفيفة وهي بتفكّر
    MELODY_CELEBRATE,   // فانفير قصير للإنجاز
    MELODY_NOTIFY,      // تنبيه لطيف
    MELODY_LOWBATT,     // بطارية واطية — هابط بطيء
    MELODY_COUNT
} sandy_melody_t;

typedef enum {
    MOTOR_STOP = 0,
    MOTOR_FORWARD,
    MOTOR_BACKWARD,
    MOTOR_LEFT,
    MOTOR_RIGHT
} motor_cmd_t;

// Global mood — written by MQTT/touch/mic handlers, read by face/buzzer tasks
extern volatile sandy_mood_t g_current_mood;
