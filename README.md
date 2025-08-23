# Twitch-ColorChanger

Changes your twitch color automatically after each message to a random one

## 📝 Setup (one-time):
To enable automatic token refresh and color changes, you must create a Twitch app to get a Client ID and Client Secret.
Steps to create a Twitch app:
1. Go to https://dev.twitch.tv/console/apps and sign in with your Twitch account.
2. Click 'Register Your Application'.
3. Enter a name for your app (e.g., 'TwitchColorBot').
4. Set 'OAuth Redirect URLs' to: https://twitchtokengenerator.com
5. Set 'Category' to 'Chat Bot' or 'Other'.
6. Click 'Create'. Your Client ID will be displayed.
7. Click 'Manage' next to your app, then 'New Secret' to generate a Client Secret. Save both values.
8. On https://twitchtokengenerator.com, select 'Custom Token Generator'.
9. Enter your Client ID and Client Secret.
10. Select scopes: chat:read, user:manage:chat_color (chat:edit optional for sending messages)
11. Click 'Generate Token' and save the Access Token and Refresh Token.

## Run in CLI
```python twitch_colorchanger.py```

## Run using Docker

You can use the following docker image : damastah/twitch-colorchanger:2
See docker-compose.yml-sample for mandatory setup for unattended operation
