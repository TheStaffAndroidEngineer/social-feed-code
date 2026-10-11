package staff.android.fieldnotes

import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.util.UUID

fun number(value: Any): Long {
    require(value is Int || value is Long)
    return (value as Number).toLong()
}

fun validatePost(post: JSONObject) {
    for (key in listOf("id", "title", "topic", "author", "body")) require(
        post.get(key) is String && post.getString(key).isNotBlank())
    require(post.get("liked") is Boolean && post.get("visible") == true)
    require(number(post.get("score")) in 0L..1000L)
}

class FeedReplica(directory: File) {
    private val file = AtomicFile(File(directory, "reading-snapshot.json"))

    private fun read(): JSONObject? {
        if (!file.baseFile.exists() && !File(file.baseFile.path + ".bak").exists()) return null
        return JSONObject(String(file.readFully(), Charsets.UTF_8)).also { validateView(it) }
    }

    private fun save(value: JSONObject) {
        validateView(value)
        val output = file.startWrite()
        try {
            output.write(value.toString().toByteArray())
            file.finishWrite(output)
        } catch (error: Exception) {
            file.failWrite(output)
            throw error
        }
    }

    fun saved(): JSONObject? = read()?.put("cached", true)

    fun open(receipt: JSONObject) {
        val id = receipt.getString("sessionId")
        UUID.fromString(id)
        if (read()?.optString("sessionId") == id) return
        save(
            JSONObject()
                .put("sessionId", id)
                .put("topic", receipt.getString("topic"))
                .put("items", JSONArray())
                .put("nextOffset", 0)
                .put("more", true)
                .put("expiresAt", 0)
                .put("snapshotRevision", 0)
                .put("observedAt", 0)
                .put("cached", true))
    }

    private fun page(api: CaseApi, cache: JSONObject, offset: Long): JSONObject {
        val response =
            api.request(
                "/feed/${cache.getString("sessionId")}?offset=$offset&topic=${URLEncoder.encode(cache.getString("topic"),"UTF-8")}")
        val page = response.getJSONObject("data")
        require(
            page.getString("sessionId") == cache.getString("sessionId") &&
                page.getString("topic") == cache.getString("topic"))
        val consumed = number(page.get("consumedPositions"))
        require(consumed in 0L..3L)
        require(number(page.get("nextOffset")) == offset + consumed)
        require(page.get("more") is Boolean && (!page.getBoolean("more") || consumed > 0))
        val items = page.getJSONArray("items")
        require(items.length() <= consumed)
        val ids = mutableSetOf<String>()
        for (i in 0 until items.length()) {
            val post = items.getJSONObject(i)
            validatePost(post)
            require(ids.add(post.getString("id")))
        }
        require(number(page.get("expiresAt")) > 0 && number(page.get("snapshotRevision")) > 0)
        if (cache.getLong("snapshotRevision") > 0)
            require(page.getLong("snapshotRevision") == cache.getLong("snapshotRevision"))
        return page.put("observedAt", response.get("observedAt"))
    }

    private fun response(cache: JSONObject) =
        JSONObject().put("observedAt", cache.get("observedAt")).put("data", cache)

    private fun merge(cache: JSONObject, page: JSONObject, replace: Boolean): JSONObject {
        val items = linkedMapOf<String, JSONObject>()
        if (!replace) {
            val existing = cache.getJSONArray("items")
            for (i in 0 until existing.length()) {
                val p = existing.getJSONObject(i)
                items[p.getString("id")] = p
            }
        }
        val incoming = page.getJSONArray("items")
        for (i in 0 until incoming.length()) {
            val p = incoming.getJSONObject(i)
            items[p.getString("id")] = p
        }
        return JSONObject(page.toString())
            .put("items", JSONArray(items.values.toList()))
            .put("cached", false)
    }

    fun refresh(api: CaseApi): JSONObject {
        val previous = read()
        if (previous == null) {
            val metadata = api.request("/view")
            return JSONObject()
                .put("observedAt", metadata.get("observedAt"))
                .put(
                    "data",
                    JSONObject()
                        .put("sessionId", JSONObject.NULL)
                        .put("items", JSONArray())
                        .put("cached", false))
        }
        val target = maxOf(3, previous.getLong("nextOffset"))
        var offset = 0L
        var work: JSONObject = previous
        repeat(34) {
            val next = page(api, previous, offset)
            work = merge(work, next, offset == 0L)
            offset = next.getLong("nextOffset")
            if (!next.getBoolean("more") || offset >= target) {
                save(work)
                return response(work)
            }
        }
        error("Snapshot exceeds bounded fixture")
    }

    fun more(api: CaseApi): JSONObject {
        val cache = read() ?: error("Open a reading snapshot first")
        if (!cache.getBoolean("more")) return response(cache)
        val next = page(api, cache, cache.getLong("nextOffset"))
        val updated = merge(cache, next, false)
        save(updated)
        return response(updated)
    }
}
