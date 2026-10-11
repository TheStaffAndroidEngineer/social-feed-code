package staff.android.fieldnotes

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import java.util.UUID

fun validateView(data:JSONObject){
    require(data.has("sessionId") && data.get("cached") is Boolean)
    if (data.isNull("sessionId")) return
    UUID.fromString(data.getString("sessionId"))
    require(data.getString("topic") in setOf("All", "Places", "Making", "People"))
    require(number(data.get("nextOffset")) in 0L..100L && data.get("more") is Boolean)
    require(
        number(data.get("expiresAt")) >= 0 &&
            number(data.get("snapshotRevision")) >= 0 &&
            number(data.get("observedAt")) >= 0)
    val items = data.getJSONArray("items")
    require(items.length() <= 100)
    val ids = mutableSetOf<String>()
    for (i in 0 until items.length()) {
        val post = items.getJSONObject(i)
        validatePost(post)
        require(ids.add(post.getString("id")))
    }
}
@Composable fun StoryArt(title: String, compact: Boolean = false) {
    val sky = Color(0xFFD8E8ED)
    val stone = Color(0xFFBEB9A7)
    val leaf = Color(0xFF467364)
    val clay = Color(0xFFB85E48)
    Canvas(Modifier.fillMaxWidth().height(if (compact) 100.dp else 210.dp)) {
        drawRect(sky)
        val w = size.width; val h = size.height
        val river = title.contains("river") || title.contains("trail") || title.contains("garden")
        if (river) {
            drawRect(Color(0xFF86AFA8), Offset(0f, h * .55f), Size(w, h * .45f))
            val bank = Path().apply { moveTo(0f, h * .6f); cubicTo(w * .3f, h * .25f, w * .6f, h * .95f, w, h * .58f); lineTo(w, h); lineTo(0f, h); close() }
            drawPath(bank, leaf)
            repeat(4) { i -> val x = w * (.12f + .24f * i); drawLine(Color(0xFF55644F), Offset(x, h * .22f), Offset(x, h * .6f), 5.dp.toPx()); drawCircle(leaf, h * .17f, Offset(x, h * .22f)) }
        } else if (title.contains("shelf") || title.contains("repair") || title.contains("mend") || title.contains("studio")) {
            drawRect(Color(0xFFE8DED0))
            drawRect(clay, Offset(w * .10f, h * .63f), Size(w * .8f, h * .09f))
            drawRect(stone, Offset(w * .14f, h * .72f), Size(w * .05f, h * .28f)); drawRect(stone, Offset(w * .81f, h * .72f), Size(w * .05f, h * .28f))
            drawRect(leaf, Offset(w * .23f, h * .27f), Size(w * .24f, h * .35f))
            drawLine(Color(0xFF69513D), Offset(w * .6f, h * .57f), Offset(w * .72f, h * .25f), 7.dp.toPx())
            drawLine(Color(0xFF516374), Offset(w * .57f, h * .27f), Offset(w * .79f, h * .38f), 12.dp.toPx())
        } else {
            drawRect(stone, Offset(0f, h * .70f), Size(w, h * .30f))
            repeat(4) { i ->
                val x = w * (.03f + i * .25f); val top = h * (.20f + (i % 2) * .12f)
                drawRect(if (i % 2 == 0) Color(0xFFD8B89E) else Color(0xFFB2C3B1), Offset(x, top), Size(w * .22f, h * .70f - top))
                repeat(2) { j -> drawRect(Color(0xFF536C71), Offset(x + w * .04f + j * w * .10f, top + h * .09f), Size(w * .05f, h * .14f)) }
                drawRect(clay, Offset(x + w * .07f, h * .53f), Size(w * .08f, h * .17f))
            }
        }
    }
}
@Composable fun Product(state:CaseState,model:CaseModel,selected:String,select:(String)->Unit){
    Text("THE EVERYDAY, OBSERVED", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
    val data=state.data
    FlowRow(horizontalArrangement=Arrangement.spacedBy(8.dp)){
        for(topic in listOf("All","Places","Making","People"))FilterChip(selected=data?.optString("topic")==topic,
            onClick={select("");model.send("open",JSONObject().put("topic",topic))},enabled=ready(state),label={Text(topic)},modifier=Modifier.testTag("topic-$topic"))
    }
    if(data==null||data.isNull("sessionId")){
        InfoCard("Take a closer look","Small stories from streets, workshops and shared spaces. Choose a topic or start with the whole collection.")
        Button(onClick={model.send("open",JSONObject().put("topic","All"))},enabled=ready(state),modifier=Modifier.testTag("open")){Text("Start reading")}
        return
    }
    if (!readingExpired(state)) {
    OutlinedButton(onClick={select("");model.send("open",JSONObject().put("topic",data.getString("topic")))},enabled=ready(state),modifier=Modifier.testTag("fresh")){Text("Check for new stories")}
    }
    Text(if(data.optBoolean("cached")||state.problem!=null)"Saved pages · latest visibility unverified" else "${data.getString("topic")} · your reading collection",style=MaterialTheme.typography.labelLarge)
    val array=data.getJSONArray("items");val posts=(0 until array.length()).map{array.getJSONObject(it)}
    val detail=posts.find{it.getString("id")==selected}
    if(detail!=null){
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
            Column(Modifier.widthIn(max = 620.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {

        TextButton(onClick={select("")},modifier=Modifier.testTag("back")){Text("Back to stories")}
        StoryArt(detail.getString("title"));SectionTitle(detail.getString("title"));Text("By ${detail.getString("author")}")
        Text(detail.getString("body"),style=MaterialTheme.typography.bodyLarge)
        Button(onClick={model.send("like",JSONObject().put("postId",detail.getString("id")).put("liked",!detail.getBoolean("liked")))},enabled=ready(state),modifier=Modifier.testTag("like")){Text(if(detail.getBoolean("liked"))"Unlike story" else "Like story")}
            }
        }
    }else{
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val fontScale = androidx.compose.ui.platform.LocalDensity.current.fontScale
            if (maxWidth >= 640.dp && fontScale <= 1.3f && posts.size > 1) {
                Row(horizontalArrangement = Arrangement.spacedBy(20.dp), verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) { StoryCard(posts.first(), true) { select(posts.first().getString("id")) } }
                    Column(Modifier.weight(1.15f), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        posts.drop(1).forEach { post -> StoryCard(post, false) { select(post.getString("id")) } }
                    }
                }
            } else Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                posts.forEachIndexed { index, post -> StoryCard(post, index == 0) { select(post.getString("id")) } }
            }
        }
        if(posts.isEmpty())InfoCard("No stories to show here","Some stories are no longer available. Continue reading if more pages are available, or check for fresh stories.")
        if(data.getBoolean("more"))Button(onClick=model::more,enabled=ready(state),modifier=Modifier.testTag("more")){Text("Load more stories")}
    }
    Text("Original demo collection · illustrations by title", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

fun readingExpired(state: CaseState): Boolean = state.problem == "This reading snapshot expired. Open a fresh snapshot; the saved pages below are the previous observation."

@Composable private fun StoryCard(post: JSONObject, featured: Boolean, onClick: () -> Unit) {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), onClick = onClick, modifier = Modifier.fillMaxWidth().testTag("story-${post.getString("id")}"), shape = RoundedCornerShape(12.dp)) {
                if (featured) {
                    StoryArt(post.getString("title"))
                    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("${post.getString("topic")} · FEATURED", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                        Text(post.getString("title"), fontWeight = FontWeight.Bold, style = MaterialTheme.typography.headlineSmall)
                        Text("By ${post.getString("author")}${if (post.getBoolean("liked")) " · Liked" else ""}", style = MaterialTheme.typography.bodySmall)
                    }
                } else {
                    Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.width(88.dp)) { StoryArt(post.getString("title"), compact = true) }
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                            Text(post.getString("topic"), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                            Text(post.getString("title"), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                            Text("${post.getString("author")}${if (post.getBoolean("liked")) " · Liked" else ""}", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
}
