from enum import IntEnum, EnumMeta


#
#
# Enum of Input
class InputEnumMeta(EnumMeta):
    def __getitem__(cls, key):
        # 如果 key 是 int，按值查找并返回名称字符串
        if isinstance(key, int):
            try:
                return cls(key).name   # 通过值获取枚举成员再取 name
            except ValueError:
                raise KeyError(f"{key} is not a valid action code")
        # 否则保留原有行为（按成员名查找）
        return super().__getitem__(key)


class MouseActionCode(IntEnum, metaclass=InputEnumMeta):

    Release = 0
    Press = 1


class KeyActionCode(IntEnum, metaclass=InputEnumMeta):

    Release = 0
    Press = 1
    Repeat = 2


class MouseButtonCode(IntEnum, metaclass=InputEnumMeta):

    Left = 0
    Right = 1
    Middle = 2
    Button4 = 3   # GLFW_MOUSE_BUTTON_4
    Button5 = 4   # GLFW_MOUSE_BUTTON_5
    Button6 = 5   # GLFW_MOUSE_BUTTON_6
    Button7 = 6   # GLFW_MOUSE_BUTTON_7
    Button8 = 7   # GLFW_MOUSE_BUTTON_8


class KeyButtonCode(IntEnum, metaclass=InputEnumMeta):
    # Printable keys (based on GLFW standard layout)
    Space = 32
    Apostrophe = 39      # '
    Comma = 44           # ,
    Minus = 45           # -
    Period = 46          # .
    Slash = 47           # /
    Num0 = 48
    Num1 = 49
    Num2 = 50
    Num3 = 51
    Num4 = 52
    Num5 = 53
    Num6 = 54
    Num7 = 55
    Num8 = 56
    Num9 = 57
    Semicolon = 59       # ;
    Equal = 61           # =
    A = 65
    B = 66
    C = 67
    D = 68
    E = 69
    F = 70
    G = 71
    H = 72
    I = 73
    J = 74
    K = 75
    L = 76
    M = 77
    N = 78
    O = 79
    P = 80
    Q = 81
    R = 82
    S = 83
    T = 84
    U = 85
    V = 86
    W = 87
    X = 88
    Y = 89
    Z = 90
    LeftBracket = 91     # [
    Backslash = 92       # \
    RightBracket = 93    # ]
    GraveAccent = 96     # `

    # Function keys
    Escape = 256
    Enter = 257
    Tab = 258
    Backspace = 259
    Insert = 260
    Delete = 261
    Right = 262
    Left = 263
    Down = 264
    Up = 265
    PageUp = 266
    PageDown = 267
    Home = 268
    End = 269
    CapsLock = 280
    ScrollLock = 281
    NumLock = 282
    PrintScreen = 283
    Pause = 284
    F1 = 290
    F2 = 291
    F3 = 292
    F4 = 293
    F5 = 294
    F6 = 295
    F7 = 296
    F8 = 297
    F9 = 298
    F10 = 299
    F11 = 300
    F12 = 301
    F13 = 302
    F14 = 303
    F15 = 304
    F16 = 305
    F17 = 306
    F18 = 307
    F19 = 308
    F20 = 309
    F21 = 310
    F22 = 311
    F23 = 312
    F24 = 313
    F25 = 314

    # Keypad keys
    KP0 = 320
    KP1 = 321
    KP2 = 322
    KP3 = 323
    KP4 = 324
    KP5 = 325
    KP6 = 326
    KP7 = 327
    KP8 = 328
    KP9 = 329
    KPDecimal = 330
    KPDivide = 331
    KPMultiply = 332
    KPSubtract = 333
    KPAdd = 334
    KPEnter = 335
    KPEqual = 336

    # Modifier keys
    LeftShift = 340
    LeftControl = 341
    LeftAlt = 342
    LeftSuper = 343
    RightShift = 344
    RightControl = 345
    RightAlt = 346
    RightSuper = 347
    Menu = 348