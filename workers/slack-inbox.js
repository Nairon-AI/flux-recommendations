/**
 * Cloudflare Worker: Slack Inbox → GitHub Action
 * 
 * Receives Slack events, extracts tweet URLs, triggers GitHub Action.
 * 
 * Environment variables needed:
 * - SLACK_SIGNING_SECRET: From Slack app settings
 * - GITHUB_TOKEN: PAT with repo access
 * - SLACK_CHANNEL_ID: Channel to watch (e.g., C0123456789)
 * 
 * Deploy:
 *   wrangler deploy
 */

const GITHUB_REPO = "Nairon-AI/flux-recommendations";

export default {
  async fetch(request, env) {
    // Handle Slack URL verification challenge
    if (request.method === "POST") {
      const body = await request.json();
      
      // URL verification (Slack sends this when setting up)
      if (body.type === "url_verification") {
        return new Response(body.challenge, {
          headers: { "Content-Type": "text/plain" },
        });
      }
      
      // Event callback
      if (body.type === "event_callback") {
        const event = body.event;
        
        // Only process messages in the target channel
        if (event.type === "message" && !event.subtype) {
          const channelId = env.SLACK_CHANNEL_ID;
          
          if (event.channel === channelId || !channelId) {
            // Extract tweet URLs
            const tweetUrls = extractTweetUrls(event.text);
            
            if (tweetUrls.length > 0) {
              // Trigger GitHub Action for each tweet
              for (const url of tweetUrls) {
                await triggerGitHubAction(env, url, event.user);
              }
              
              // Optionally react to the message
              if (env.SLACK_BOT_TOKEN) {
                await addSlackReaction(env, event.channel, event.ts, "eyes");
              }
            }
          }
        }
      }
      
      return new Response("OK", { status: 200 });
    }
    
    return new Response("Flux Slack Inbox Worker", { status: 200 });
  },
};

function extractTweetUrls(text) {
  if (!text) return [];
  
  const patterns = [
    /https?:\/\/(?:www\.)?twitter\.com\/\w+\/status\/\d+/g,
    /https?:\/\/(?:www\.)?x\.com\/\w+\/status\/\d+/g,
  ];
  
  const urls = [];
  for (const pattern of patterns) {
    const matches = text.match(pattern);
    if (matches) {
      urls.push(...matches);
    }
  }
  
  return [...new Set(urls)]; // Dedupe
}

async function triggerGitHubAction(env, tweetUrl, slackUser) {
  const response = await fetch(
    `https://api.github.com/repos/${GITHUB_REPO}/dispatches`,
    {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": `token ${env.GITHUB_TOKEN}`,
        "User-Agent": "FluxSlackInbox/1.0",
      },
      body: JSON.stringify({
        event_type: "slack-tweet",
        client_payload: {
          tweet_url: tweetUrl,
          slack_user: slackUser || "unknown",
        },
      }),
    }
  );
  
  if (!response.ok) {
    console.error(`GitHub API error: ${response.status}`);
  }
  
  return response.ok;
}

async function addSlackReaction(env, channel, timestamp, emoji) {
  try {
    await fetch("https://slack.com/api/reactions.add", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.SLACK_BOT_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        channel: channel,
        timestamp: timestamp,
        name: emoji,
      }),
    });
  } catch (e) {
    console.error("Failed to add reaction:", e);
  }
}
