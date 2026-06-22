# Sandy — Product Vision

> The "why and what" of the product. Read this with `PRODUCT_MIGRATION_PLAN.md`
> (which holds the "how" of the backend migration). This doc is English by repo
> convention; chat with the owner is Arabic.

## One line

Sandy is a voice-first personal assistant that lives in an app, manages your work
life (tasks, appointments, email), and can reach into the physical world to control
ordinary, non-smart devices through cheap learnable add-ons. Sold to both
**companies** (employee offices) and **homes**.

## The three product layers

The product is three independent things that are sold and adopted separately. None
forces the others.

1. **The App (the brain + the subscription).** This is THE product. The assistant
   talks, manages tasks, reminders, appointments, and email. It scales for free,
   ships instantly to everyone, and carries the recurring revenue. Everything else
   is optional hardware that plugs into it.

2. **Extensions (the actuators).** Small, cheap, plug-and-play hardware pieces that
   mount onto an ordinary device (a wall switch, an AC, curtains, a door lock) and
   let the app control it. They work on their own over the network; the robot is
   NOT required to use them. This is what turns a "chat assistant" into real-world
   control without needing the device to be smart in the first place.

3. **The Robot (voice + presence).** A premium piece for a room. Its value is
   hands-free: talk to control the room, hear reminders and appointments, no phone,
   no Siri/Google. When present it can act as the room's voice gateway and the
   coordinator for nearby extensions. When absent, extensions still work straight
   from the app.

## Positioning (the marketing call)

**The app/platform is the product. The robot is the flagship accessory, not the
core.** Reasons:

- Software scales at zero marginal cost and earns a recurring subscription.
  Hardware is slow and capped by a production line (manufacturing, shipping,
  support, thin margins). Tying the whole product to the robot would cap growth.
- A bigger market opens when the robot is optional: every employee and every home
  can start with just the app plus a cheap extension. Forcing a robot on every desk
  spikes the price and slows adoption.
- The brain already lives in the cloud. The robot is just one "body" for Sandy in
  one room. Keep it optional.

The robot is still the marketing magnet, the "wow" that earns press and attention.
So the balance is:

> The robot is the **face of the brand** (it draws people in). The app + extensions
> are the **actual product and revenue**.

Message to the market: "Sandy is an assistant that lives in your pocket (the app).
If you want presence and voice in a room, add her body (the robot)."

## The extension model

The point is generality. It is not a fixed list of supported devices; it is a
**programmable, learnable** system where the app defines what each piece does.

- **Learnable, plug-and-play setup.** You buy a ready piece. In the app you pick
  "set up my AC remote", point the old remote at the piece, it captures the signal
  and asks "what does this do?", and stores it. Then you place the piece and Sandy
  controls the device by voice ("Sandy, turn on the AC").
- **Universal, not per-device.** The same flow covers AC, lighting, curtains,
  door open/close/lock, and anything driven by a remote or a switch. Adding a new
  kind of action should not require changing the app each time.
- **Software-defined.** One shared definition/messaging protocol so any new
  extension is just an extension of the same pattern, not a new system.

## Hardware approach

- **Cheap, capable controllers (the ESP32 family).** They have networking and can
  drive an IR blaster (to learn/replay remote signals), a relay (for switches), and
  a motor (for curtains/locks). A smaller/cheaper variant fits single-purpose pieces
  (one switch); the larger variant powers the robot.
- **This is a generalization of the existing `room-node`.** The current room node
  (lights/fan/curtain over MQTT) is already exactly this idea. The product turns it
  into a learnable, sellable, ready-made piece bound to a tenant, talking to the
  same backend over the same messaging protocol. New system: no. Same pattern,
  productized.

## How it maps to the multi-tenant architecture

This vision and the migration plan are the same work, not two tracks.

- **A company is a tenant** with many employees (users), offices/rooms (spaces),
  and devices. The strict per-tenant isolation being built is exactly what this
  needs.
- **A home is a tenant** too, just simpler.
- **The robot and the extensions are a tenant's integrations**, bound to that
  tenant, not global code. This is precisely what the migration plan already states
  ("the robot/room become his tenant's integrations, not global code").

So the multi-tenant backend and strict isolation being built now is the same
foundation this product needs. It is not extra work bolted on later.

## Open questions / decisions

- **Extension connectivity:** does each extension join the network directly (easier
  install, slightly pricier per piece) or talk through one cheap hub per place
  (cheaper pieces, but one extra unit to buy)? Leaning toward **direct-connect
  extensions first** for the simplest install; defer the hub.
- **Robot-as-hub:** if a robot is present, should it double as the room's gateway
  and coordinator for nearby extensions? Leaning yes, but it must stay optional.
- Pricing/packaging of the three layers (app subscription vs per-extension vs robot).
- Spaces/devices data model inside a tenant (rooms, device registry, learned signal
  store) — to be designed when extension work starts.
