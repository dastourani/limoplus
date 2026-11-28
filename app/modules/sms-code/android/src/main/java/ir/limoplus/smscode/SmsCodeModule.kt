package ir.limoplus.smscode

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.util.Base64
import com.google.android.gms.auth.api.phone.SmsRetriever
import com.google.android.gms.common.api.CommonStatusCodes
import com.google.android.gms.common.api.Status
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.nio.charset.StandardCharsets
import java.security.MessageDigest

/**
 * Reads the login code from the SMS automatically (Google SMS Retriever API).
 * No SMS permission: Android hands over only the one message that ends with this app's 11-character hash,
 * for up to 5 minutes after start() is called.
 */
class SmsCodeModule : Module() {
  private var receiver: BroadcastReceiver? = null

  private val context: Context
    get() = requireNotNull(appContext.reactContext) { "React context is not available" }

  override fun definition() = ModuleDefinition {
    Name("SmsCode")

    Events("onSms")

    /** The hash the server must put on the last line of the SMS (depends on the app's signing key). */
    Function("getHash") {
      return@Function appHash(context)
    }

    AsyncFunction("start") {
      stop()
      val ctx = context
      val r = object : BroadcastReceiver() {
        override fun onReceive(c: Context?, intent: Intent?) {
          if (intent?.action != SmsRetriever.SMS_RETRIEVED_ACTION) return
          val extras = intent.extras ?: return
          val status = if (Build.VERSION.SDK_INT >= 33) {
            extras.getParcelable(SmsRetriever.EXTRA_STATUS, Status::class.java)
          } else {
            @Suppress("DEPRECATION") extras.get(SmsRetriever.EXTRA_STATUS) as? Status
          }
          when (status?.statusCode) {
            CommonStatusCodes.SUCCESS -> sendEvent("onSms", mapOf("message" to (extras.getString(SmsRetriever.EXTRA_SMS_MESSAGE) ?: "")))
            CommonStatusCodes.TIMEOUT -> sendEvent("onSms", mapOf("timeout" to true))
          }
        }
      }
      val filter = IntentFilter(SmsRetriever.SMS_RETRIEVED_ACTION)
      if (Build.VERSION.SDK_INT >= 33) {
        ctx.registerReceiver(r, filter, SmsRetriever.SEND_PERMISSION, null, Context.RECEIVER_EXPORTED)
      } else {
        ctx.registerReceiver(r, filter, SmsRetriever.SEND_PERMISSION, null)
      }
      receiver = r
      SmsRetriever.getClient(ctx).startSmsRetriever()
      return@AsyncFunction true
    }

    Function("stop") {
      stop()
    }

    OnDestroy {
      stop()
    }
  }

  private fun stop() {
    receiver?.let {
      try {
        context.unregisterReceiver(it)
      } catch (_: Exception) {
      }
    }
    receiver = null
  }

  private fun appHash(ctx: Context): String? {
    return try {
      val pm = ctx.packageManager
      val signatures = if (Build.VERSION.SDK_INT >= 28) {
        val info = pm.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
        info.signingInfo?.apkContentsSigners
      } else {
        @Suppress("DEPRECATION")
        pm.getPackageInfo(ctx.packageName, PackageManager.GET_SIGNATURES).signatures
      }
      val signature = signatures?.firstOrNull() ?: return null
      val appInfo = ctx.packageName + " " + signature.toCharsString()
      val digest = MessageDigest.getInstance("SHA-256")
      digest.update(appInfo.toByteArray(StandardCharsets.UTF_8))
      val hashSignature = digest.digest().copyOfRange(0, 9)
      Base64.encodeToString(hashSignature, Base64.NO_PADDING or Base64.NO_WRAP).substring(0, 11)
    } catch (e: Exception) {
      null
    }
  }
}
