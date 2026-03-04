/**
 * Cloudflare Worker: Slack Inbox → GitHub Action
 * 
 * Receives Slack events, extracts URLs (tweets, YouTube, GitHub, etc.),
 * triggers GitHub Action for analysis.
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
        
        // Ignore bot messages and thread replies
        if (event.bot_id || event.thread_ts) {
          return new Response("OK", { status: 200 });
        }
        
        // Only process messages in the target channel
        if (event.type === "message" && !event.subtype) {
          const channelId = env.SLACK_CHANNEL_ID;
          
          if (event.channel === channelId || !channelId) {
            // Extract all URLs
            const urls = extractUrls(event.text);
            
            if (urls.length > 0) {
              // Trigger GitHub Action for each URL
              for (const url of urls) {
                await triggerGitHubAction(env, url, event.user, event.channel, event.ts);
              }
              
              // React to the message
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

function extractUrls(text) {
  if (!text) return [];
  
  // Match any URL - http/https with common TLDs
  const urlPattern = /https?:\/\/[^\s<>\"']+/g;
  const matches = text.match(urlPattern);
  
  if (!matches) return [];
  
  // Clean up URLs (remove trailing punctuation)
  const cleaned = matches.map(url => url.replace(/[.,;:!?)>\]]+$/, ''));
  
  // Filter to supported domains (expand as needed)
  const supportedDomains = [
    'twitter.com', 'x.com',           // Tweets
    'youtube.com', 'youtu.be',        // Videos
    'github.com',                     // Repos
    'npmjs.com', 'pypi.org',          // Packages
    'dev.to', 'medium.com',           // Articles
    'blog.', 'docs.',                 // Blogs, docs
  ];
  
  const filtered = cleaned.filter(url => {
    // Allow all URLs for now - Exa can handle most things
    return true;
  });
  
  return [...new Set(filtered)]; // Dedupe
}

async function triggerGitHubAction(env, url, slackUser, channel, timestamp) {
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
        event_type: "slack-url",
        client_payload: {
          url: url,
          tweet_url: url,  // Backward compat
          slack_user: slackUser || "unknown",
          slack_channel: channel,
          slack_ts: timestamp,
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
