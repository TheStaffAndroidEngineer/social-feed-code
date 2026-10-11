package staff.android.fieldnotes

import android.Manifest
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.rule.GrantPermissionRule
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assert.assertEquals
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class FeedJourneyTest {
    @get:Rule(order=0)val permission=GrantPermissionRule.grant(Manifest.permission.ACCESS_LOCAL_NETWORK)
    @get:Rule(order=1)val compose=createAndroidComposeRule<MainActivity>()
    @Test fun stableOrderHidingAndExpiry(){
        try {
            waitTag("open");tap("open");waitTag("story-post-01")
            command("publish",JSONObject().put("postId","new-story").put("title","The new morning walk").put("topic","Places").put("score",999))
            tap("more");waitReady();assertEquals(6,cache().getJSONArray("items").length())
            assertEquals("post-01",cache().getJSONArray("items").getJSONObject(0).getString("id"))
            command("hide",JSONObject().put("postId","post-01"));tap("refresh");waitReady()
            assertEquals(5,cache().getJSONArray("items").length());assertEquals(6,cache().getInt("nextOffset"))
            tap("fresh");waitReady();assertEquals("new-story",cache().getJSONArray("items").getJSONObject(0).getString("id"))
            request("/__control","{\"advance_ms\":120000}");tap("more");waitReady()
            assertEquals(3,cache().getInt("nextOffset"))
            compose.onNodeWithText("Connection and recovery").assertExists()
            compose.onNodeWithTag("fresh").performScrollTo().assertIsDisplayed()
            val expiredSessionId = cache().getString("sessionId")
            tap("fresh");waitReady()
            assertEquals(false, expiredSessionId == cache().getString("sessionId"))
            compose.onNodeWithText("Connection and recovery").assertDoesNotExist()
            assertEquals(3,cache().getInt("nextOffset"))
            assertEquals("new-story",cache().getJSONArray("items").getJSONObject(0).getString("id"))
        }finally{request("/__control","{}")}
    }
    private fun cache()=JSONObject(File(InstrumentationRegistry.getInstrumentation().targetContext.filesDir,"reading-snapshot.json").readText())
    private fun command(action:String,args:JSONObject)=request("/commands",JSONObject().put("id",UUID.randomUUID().toString()).put("action",action).put("args",args).toString())
    private fun tap(tag:String){
        val node = compose.onNodeWithTag(tag)
        if (tag in setOf("refresh", "lab-tab")) node.performClick() else node.performScrollTo().performClick()
    }
    private fun waitTag(tag:String){compose.waitUntil(30000){compose.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty()};waitReady()}
    private fun waitReady(){compose.waitUntil(30000){compose.onAllNodesWithTag("busy").fetchSemanticsNodes().isEmpty()}}
    private fun request(path:String,body:String?=null):JSONObject{
        val connection=URL("http://10.0.2.2:8916$path").openConnection() as HttpURLConnection
        connection.connectTimeout=5000;connection.readTimeout=5000
        if(body!=null){connection.requestMethod="POST";connection.doOutput=true;connection.setRequestProperty("Content-Type","application/json");connection.outputStream.use{it.write(body.toByteArray())}}
        return try{JSONObject(connection.inputStream.bufferedReader().use{it.readText()})}finally{connection.disconnect()}
    }
}
